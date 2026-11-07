#!/usr/bin/env python3
"""Report EQCORR policy counterfactuals from the journals of a completed run.

Kept separate from the runner because the runner's poll loop cannot terminate on
its own: trades whose entry chain yields no candidate return NO_CANDIDATE and are
never marked processed, so every poll re-reports them as "closes" and the idle
condition never trips. The journals are complete regardless, so results are
computed from them directly.

Reported on train + validation only. The holdout in
config/research/etll_hybrid_calibration_split.json is opened once, for one final
configuration; a descriptive sweep over 18 policies is not that moment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
sys.path.insert(0, str(ROOT))

from calibration_split import assign_segment, load_split  # noqa: E402

STAGE_ROOT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr"
DEFAULT_EPOCH = "ETLL_HYBRID_TICK_V1_20260905_092610"
REPORTED_SEGMENTS = ("train", "validation")

KEY_POLICIES = (
    "BASELINE_ALL_ELIGIBLE",
    "MAX_1_SAME_DIRECTION",
    "MAX_2_SAME_DIRECTION",
    "MAX_3_SAME_DIRECTION",
    "ONE_TACTICAL_ONE_STRUCTURAL",
    "PROGRESSIVE_RISK_REDUCTION",
    "DIRECTION_RISK_CAP_100_BLOCK",
    "DIRECTION_RISK_CAP_100_REDUCE",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def stats(pnls: list[float], risk: float = 1000.0) -> dict[str, Any]:
    if not pnls:
        return {"n": 0}
    s = pd.Series(pnls, dtype=float)
    wins = s[s > 0]
    losses = s[s < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else None
    return {
        "n": int(len(s)),
        "wr_pct": round(float((s > 0).mean()) * 100, 2),
        "net_pnl_usd": round(float(s.sum()), 2),
        "avg_pnl_usd": round(float(s.mean()), 2),
        "expectancy_r": round(float(s.mean() / risk), 4),
        "profit_factor": round(pf, 3) if pf else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    args = parser.parse_args()

    epoch = args.epoch_id
    books = STAGE_ROOT / "paper_repo/data/trading/intrabar_paper" / epoch / "books"
    shadow = (
        STAGE_ROOT
        / "paper_repo/data/trading/shadow_economic_correlation/epochs"
        / epoch
    )

    trades = pd.DataFrame(read_jsonl(books / "trades.jsonl"))
    trades["position_id"] = trades["position_id"].astype(str)
    trades["net_pnl_usd"] = pd.to_numeric(trades["net_pnl_usd"], errors="coerce").fillna(0.0)
    trades["segment"] = assign_segment(trades)

    candidates = read_jsonl(shadow / "candidate_snapshots.jsonl")
    decisions = read_jsonl(shadow / "policy_decisions.jsonl")
    enrichments = read_jsonl(shadow / "candidate_feature_enrichments.jsonl")
    outcomes = read_jsonl(shadow / "quality_outcomes.jsonl")

    cand_to_pos = {
        str(c["candidate_id"]): str(c["position_id"])
        for c in candidates
        if c.get("candidate_id") and c.get("position_id")
    }

    reported = trades.loc[trades["segment"].isin(REPORTED_SEGMENTS)]
    pos_pnl = reported.set_index("position_id")["net_pnl_usd"].astype(float).to_dict()

    executed: dict[str, list[float]] = {}
    blocked: dict[str, list[float]] = {}
    counts: dict[str, dict[str, int]] = {}
    for row in decisions:
        if row.get("record_type"):
            continue
        policy = str(row.get("policy_id") or "")
        cid = str(row.get("candidate_id") or "")
        action = str(row.get("action") or "")
        pid = cand_to_pos.get(cid)
        if not policy or pid is None or pid not in pos_pnl:
            continue
        pnl = float(pos_pnl[pid])
        mult = float(row.get("risk_multiplier") or 1.0)
        counts.setdefault(policy, {})
        counts[policy][action] = counts[policy].get(action, 0) + 1
        if action in {"EXECUTE_FULL", "EXECUTE_REDUCED"}:
            executed.setdefault(policy, []).append(pnl * mult)
        elif "BLOCK" in action.upper():
            blocked.setdefault(policy, []).append(pnl)

    policies: dict[str, Any] = {}
    for policy in sorted(set(executed) | set(blocked) | set(counts)):
        total = sum(counts.get(policy, {}).values())
        blocks = sum(v for k, v in counts.get(policy, {}).items() if "BLOCK" in k.upper())
        ex = stats(executed.get(policy, []))
        bl = stats(blocked.get(policy, []))
        policies[policy] = {
            "executed": ex,
            "blocked_would_be": bl,
            "block_rate_pct": round(blocks / total * 100, 2) if total else None,
            "candidates_seen": total,
            "pnl_vs_baseline_usd": None,
        }

    base = policies.get("BASELINE_ALL_ELIGIBLE", {}).get("executed", {})
    base_pnl = float(base.get("net_pnl_usd") or 0.0)
    for name, entry in policies.items():
        got = float(entry["executed"].get("net_pnl_usd") or 0.0)
        entry["pnl_vs_baseline_usd"] = round(got - base_pnl, 2)

    unclosed = int(len(trades)) - len(outcomes)
    summary = {
        "stage": "ETLL_SHADOW_EQCORR_HYBRID_TICK_REPORT",
        "epoch_id": epoch,
        "book": "canonical Hybrid tick (S4.1 manager + LIVE1B intrabar), market-time staged",
        "timeframes": ["M15", "M30", "H1", "H4"],
        "trades_in_book": int(len(trades)),
        "candidates": len(candidates),
        "decision_rows": sum(1 for r in decisions if not r.get("record_type")),
        "outcome_attachments": sum(1 for r in decisions if r.get("record_type")),
        "enrichments": len(enrichments),
        "quality_outcomes": len(outcomes),
        "trades_without_candidate": unclosed,
        "lookahead_detected_enrichments": sum(1 for r in enrichments if r.get("lookahead_detected")),
        "lookahead_detected_decisions": sum(
            1 for r in decisions if not r.get("record_type") and r.get("lookahead_detected")
        ),
        "segments_reported": list(REPORTED_SEGMENTS),
        "holdout_status": "SEALED — not evaluated",
        "trades_reported": int(len(reported)),
        "segment_breakdown": {
            seg: stats(trades.loc[trades["segment"] == seg, "net_pnl_usd"].tolist())
            for seg in ("train", "validation", "holdout", "purged")
        },
        "policies": policies,
        "split_reference": load_split()["reference_book"]["paper_epoch_id"],
    }

    out_dir = STAGE_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "shadow_eqcorr_hybrid_tick_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    # Console table, key policies first.
    print(f"\nEQCORR on Hybrid tick book — {epoch}")
    print(f"train+validation trades: {len(reported)} of {len(trades)}   (holdout sealed)")
    print(
        f"lookahead flags: enrichments={summary['lookahead_detected_enrichments']} "
        f"decisions={summary['lookahead_detected_decisions']}"
    )
    print()
    hdr = f"{'policy':<32}{'exec':>6}{'blk%':>7}{'WR%':>7}{'expR':>8}{'PF':>7}{'net_pnl':>13}{'vs_base':>13}{'blocked_pnl':>13}"
    print(hdr)
    print("-" * len(hdr))
    order = [p for p in KEY_POLICIES if p in policies] + [
        p for p in sorted(policies) if p not in KEY_POLICIES
    ]
    for p in order:
        e = policies[p]["executed"]
        b = policies[p]["blocked_would_be"]
        print(
            f"{p:<32}{e.get('n', 0):>6}{policies[p]['block_rate_pct'] or 0:>7.1f}"
            f"{e.get('wr_pct') or 0:>7.1f}{e.get('expectancy_r') or 0:>8.3f}"
            f"{e.get('profit_factor') or 0:>7.2f}{e.get('net_pnl_usd') or 0:>13,.0f}"
            f"{policies[p]['pnl_vs_baseline_usd']:>13,.0f}{b.get('net_pnl_usd') or 0:>13,.0f}"
        )
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
