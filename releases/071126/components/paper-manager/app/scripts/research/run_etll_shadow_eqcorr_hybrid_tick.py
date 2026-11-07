#!/usr/bin/env python3
"""Shadow EQCORR on the canonical Hybrid tick book (M15+M30+H1+H4 in one epoch).

This is the correlation test that means something: the Hybrid book is already a
single combined multi-timeframe epoch, so concurrent exposure across timeframes is
visible to the policies. Per-timeframe EQCORR cannot see correlation at all.

Two deliberate differences from run_etll_shadow_eqcorr_multi_tf_lived.py:

1. It reads the market-time staging produced by stage_hybrid_book_for_eqcorr.py
   rather than merging four per-timeframe bar-close packs. The Hybrid replay stamps
   books with wall-clock time, which would make the causal enricher's as-of joins
   match the newest cognition row for every candidate.

2. Results are reported on train and validation only. The holdout defined in
   config/research/etll_hybrid_calibration_split.json is opened once, for one final
   configuration; a descriptive sweep across nine policies is not that moment.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
# parquet_utils lives at the repo root, and the cognition imports pulled in by the
# EQCORR engine reach for it as a top-level module.
sys.path.insert(0, str(ROOT))

from btc_ml.trading.shadow_economic_correlation.engine import (  # noqa: E402
    ShadowEconomicCorrelationEngine,
)
from calibration_split import assign_segment, load_split  # noqa: E402
from run_etll_shadow_eqcorr_multi_tf_lived import (  # noqa: E402
    KEY_POLICIES,
    _bucket_stats,
    _read_jsonl,
)
from stage_hybrid_book_for_eqcorr import STAGE_ROOT, stage  # noqa: E402

DEFAULT_EPOCH = "ETLL_HYBRID_TICK_V1_20260905_092610"
DEFAULT_ARCHIVE = Path("/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive")
REPORTED_SEGMENTS = ("train", "validation")


def _lived_from_staged(books: Path) -> pd.DataFrame:
    rows = _read_jsonl(books / "trades.jsonl")
    frame = pd.DataFrame(rows)
    frame["position_id"] = frame["position_id"].astype(str)
    frame["net_pnl_usd"] = pd.to_numeric(frame.get("net_pnl_usd"), errors="coerce").fillna(0.0)
    frame["segment"] = assign_segment(frame)
    return frame


def _counterfactuals(
    *,
    lived: pd.DataFrame,
    candidates: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    segments: tuple[str, ...],
) -> dict[str, Any]:
    """Per-policy executed / blocked PnL, restricted to the named segments.

    A blocked candidate's PnL is what the real book actually earned on that trade,
    so "blocked_would_be_pnl" being positive means the policy gave up money.
    """
    cand_to_pos = {
        str(c["candidate_id"]): str(c["position_id"])
        for c in candidates
        if c.get("candidate_id") and c.get("position_id")
    }
    keep = lived.loc[lived["segment"].isin(segments)]
    pos_pnl = keep.set_index("position_id")["net_pnl_usd"].astype(float).to_dict()

    executed: dict[str, list[float]] = {}
    blocked: dict[str, list[float]] = {}
    actions: dict[str, dict[str, int]] = {}

    for row in decisions:
        # The journal interleaves decisions with OUTCOME_ATTACHMENT rows that carry
        # the same policy_id/candidate_id but no action. Counting both doubles the
        # denominator behind block_rate.
        if row.get("record_type"):
            continue
        cid = str(row.get("candidate_id") or "")
        policy = str(row.get("policy_id") or "")
        action = str(row.get("action") or "")
        if not cid or not policy:
            continue
        pid = cand_to_pos.get(cid)
        if pid is None or pid not in pos_pnl:
            continue
        pnl = float(pos_pnl[pid])
        mult = float(row.get("risk_multiplier") or 1.0)
        actions.setdefault(policy, {})
        actions[policy][action] = actions[policy].get(action, 0) + 1
        if action in {"EXECUTE_FULL", "EXECUTE_REDUCED"}:
            executed.setdefault(policy, []).append(pnl * mult)
        elif "BLOCK" in action.upper():
            blocked.setdefault(policy, []).append(pnl)

    out: dict[str, Any] = {}
    for policy in sorted(set(executed) | set(blocked) | set(actions)):
        total = sum(actions.get(policy, {}).values())
        blocks = sum(v for k, v in actions.get(policy, {}).items() if "BLOCK" in k.upper())
        out[policy] = {
            "executed": _bucket_stats(executed.get(policy, [])),
            "blocked_would_be_pnl": _bucket_stats(blocked.get(policy, [])),
            "block_rate": round(blocks / total, 4) if total else None,
            "actions": dict(actions.get(policy, {})),
        }
    return out


def run(
    *,
    epoch_id: str,
    archive_root: Path,
    skip_stage: bool,
    fresh: bool,
    max_idle_polls: int,
    max_polls: int,
) -> dict[str, Any]:
    stage_summary: dict[str, Any] | None = None
    if not skip_stage:
        stage_summary = stage(epoch_id=epoch_id, archive_root=archive_root, fresh=True)

    paper_repo = STAGE_ROOT / "paper_repo"
    books = paper_repo / "data" / "trading" / "intrabar_paper" / epoch_id / "books"
    if not books.exists():
        raise FileNotFoundError(f"staged books missing: {books} (run without --skip-stage)")

    # assert_shadow_write_path refuses anything outside the repo's own shadow root,
    # so the epoch state has to live inside the staged paper_repo.
    shadow_dir = (
        paper_repo / "data" / "trading" / "shadow_economic_correlation" / "epochs" / epoch_id
    )
    if fresh and shadow_dir.exists():
        shutil.rmtree(shadow_dir)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    reports = STAGE_ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    engine = ShadowEconomicCorrelationEngine(
        repo=paper_repo,
        epoch_id=epoch_id,
        strict_epoch=False,
        shadow_dir=shadow_dir,
    )

    started = time.time()
    polls: list[dict[str, Any]] = []
    idle = 0
    while idle < max_idle_polls and len(polls) < max_polls:
        poll = engine.poll_once()
        entry = {k: poll.get(k) for k in ("entries", "closes", "enrichments", "poll_ms")}
        polls.append(entry)
        moved = (poll.get("entries") or 0) + (poll.get("closes") or 0) + (poll.get("enrichments") or 0)
        idle = idle + 1 if moved == 0 else 0
        if len(polls) % 5 == 0:
            done = sum((p.get("entries") or 0) for p in polls)
            print(
                f"[eqcorr] poll={len(polls)} entries_total={done} "
                f"elapsed={time.time() - started:.0f}s",
                flush=True,
            )
    elapsed = time.time() - started

    files = {p.name: p for p in shadow_dir.rglob("*.jsonl")}
    candidates = _read_jsonl(files.get("candidate_snapshots.jsonl", shadow_dir / "candidate_snapshots.jsonl"))
    decisions = _read_jsonl(files.get("policy_decisions.jsonl", shadow_dir / "policy_decisions.jsonl"))
    enrichments = _read_jsonl(
        files.get("candidate_feature_enrichments.jsonl", shadow_dir / "candidate_feature_enrichments.jsonl")
    )

    lived = _lived_from_staged(books)
    split = load_split()
    reported = lived.loc[lived["segment"].isin(REPORTED_SEGMENTS)]

    policy_stats = _counterfactuals(
        lived=lived,
        candidates=candidates,
        decisions=decisions,
        segments=REPORTED_SEGMENTS,
    )

    lookahead = sum(1 for r in enrichments if r.get("lookahead_detected"))
    summary: dict[str, Any] = {
        "stage": "ETLL_SHADOW_EQCORR_HYBRID_TICK",
        "epoch_id": epoch_id,
        "timeframes": ["M15", "M30", "H1", "H4"],
        "book": "canonical Hybrid tick (S4.1 manager + LIVE1B intrabar), market-time staged",
        "elapsed_s": round(elapsed, 1),
        "polls": len(polls),
        "candidates": len(candidates),
        "policy_decisions": len(decisions),
        "enrichments": len(enrichments),
        "lookahead_detected_rows": lookahead,
        "trades_in_book": int(len(lived)),
        "segments_reported": list(REPORTED_SEGMENTS),
        "holdout_status": "SEALED — not evaluated in this run",
        "trades_reported": int(len(reported)),
        "baseline_reported_segments": _bucket_stats(reported["net_pnl_usd"].astype(float).tolist()),
        "segment_breakdown": {
            seg: _bucket_stats(
                lived.loc[lived["segment"] == seg, "net_pnl_usd"].astype(float).tolist()
            )
            for seg in REPORTED_SEGMENTS
        },
        "policy_counterfactuals": {p: policy_stats[p] for p in KEY_POLICIES if p in policy_stats},
        "all_policy_ids": sorted(policy_stats),
        "split_reference": split["reference_book"]["paper_epoch_id"],
        "artifacts": {
            "staged_books": str(books),
            "shadow_eqcorr": str(shadow_dir),
            "reports": str(reports),
        },
    }
    if stage_summary is not None:
        summary["staging"] = {
            "market_end": stage_summary["market_end"],
            "tables": stage_summary["tables"],
        }

    out = reports / "shadow_eqcorr_hybrid_tick_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    summary["artifacts"]["summary_json"] = str(out)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--skip-stage", action="store_true")
    parser.add_argument("--no-fresh", action="store_true")
    parser.add_argument("--max-idle-polls", type=int, default=3)
    parser.add_argument("--max-polls", type=int, default=5000)
    args = parser.parse_args()
    summary = run(
        epoch_id=args.epoch_id,
        archive_root=args.archive_root,
        skip_stage=args.skip_stage,
        fresh=not args.no_fresh,
        max_idle_polls=args.max_idle_polls,
        max_polls=args.max_polls,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
