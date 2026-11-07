#!/usr/bin/env python3
"""ETLL: Shadow EQCORR on combined M15+M30+H1+H4 canonical lived books.

This is the meaningful correlation test — all timeframes in one epoch.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import (  # noqa: E402
    MULTI_TF_EPOCH_ID,
    adapt_multi_tf_lived_books_to_jsonl,
    ensure_lab_dirs,
    link_pack_cognition_for_eqcorr,
    multi_tf_paths,
)
from btc_ml.trading.shadow_economic_correlation.engine import (  # noqa: E402
    ShadowEconomicCorrelationEngine,
)

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


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _bucket_stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0}
    s = pd.Series(pnls, dtype=float)
    return {
        "n": int(len(s)),
        "wr": float((s > 0).mean()),
        "net_pnl_usd": float(s.sum()),
        "avg_pnl_usd": float(s.mean()),
        "wins": int((s > 0).sum()),
        "losses": int((s < 0).sum()),
    }


def _policy_counterfactuals(
    *,
    lived: pd.DataFrame,
    candidates: list[dict],
    decisions: list[dict],
) -> dict[str, dict]:
    cand_to_pos = {str(c["candidate_id"]): str(c["position_id"]) for c in candidates if c.get("candidate_id")}
    pos_pnl = lived.set_index(lived["position_id"].astype(str))["net_pnl_usd"].astype(float).to_dict()

    by_policy: dict[str, list[float]] = defaultdict(list)
    blocked_pnl: dict[str, list[float]] = defaultdict(list)
    action_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in decisions:
        cid = str(row.get("candidate_id") or "")
        policy = str(row.get("policy_id") or "")
        action = str(row.get("action") or "")
        if not cid or not policy:
            continue
        pid = cand_to_pos.get(cid)
        if not pid or pid not in pos_pnl:
            continue
        pnl = float(pos_pnl[pid])
        mult = float(row.get("risk_multiplier") or 1.0)
        action_counts[policy][action] += 1
        if action in {"EXECUTE_FULL", "EXECUTE_REDUCED"}:
            by_policy[policy].append(pnl * mult)
        elif "BLOCK" in action.upper():
            blocked_pnl[policy].append(pnl)

    out: dict[str, dict] = {}
    for policy in sorted(set(by_policy) | set(blocked_pnl) | set(action_counts)):
        executed = _bucket_stats(by_policy.get(policy, []))
        blocked = _bucket_stats(blocked_pnl.get(policy, []))
        total_candidates = sum(action_counts[policy].values())
        out[policy] = {
            "executed": executed,
            "blocked_would_be_pnl": blocked,
            "block_rate": float(action_counts[policy].get("BLOCK_CORRELATED_EXPOSURE", 0) / total_candidates)
            if total_candidates
            else None,
            "actions": dict(action_counts[policy]),
        }
    return out


def run_multi_tf_eqcorr(
    *,
    skip_adapt: bool = False,
    limit_trades: int | None = None,
    fresh: bool = True,
    max_idle_polls: int = 5,
) -> dict:
    paths = multi_tf_paths()
    epoch = MULTI_TF_EPOCH_ID
    ensure_lab_dirs(paths)

    if fresh and paths["shadow_eqcorr"].exists():
        shutil.rmtree(paths["shadow_eqcorr"])
        paths["shadow_eqcorr"].mkdir(parents=True, exist_ok=True)

    if not skip_adapt:
        adapt_multi_tf_lived_books_to_jsonl(limit_trades=limit_trades)

    link_pack_cognition_for_eqcorr(paths)

    engine = ShadowEconomicCorrelationEngine(
        repo=paths["paper_repo"],
        epoch_id=epoch,
        strict_epoch=False,
        shadow_dir=paths["shadow_eqcorr"],
    )

    polls = []
    idle_streak = 0
    while idle_streak < max_idle_polls:
        poll = engine.poll_once()
        polls.append({k: poll.get(k) for k in ("entries", "closes", "enrichments", "poll_ms")})
        if poll.get("entries", 0) == 0 and poll.get("closes", 0) == 0 and poll.get("enrichments", 0) == 0:
            idle_streak += 1
        else:
            idle_streak = 0

    eq_dir = paths["shadow_eqcorr"]
    eq_files = {p.name: p for p in eq_dir.rglob("*.jsonl")}
    candidates = _read_jsonl(eq_files.get("candidate_snapshots.jsonl", eq_dir / "candidate_snapshots.jsonl"))
    decisions = _read_jsonl(eq_files.get("policy_decisions.jsonl", eq_dir / "policy_decisions.jsonl"))

    lived = pd.read_parquet(paths["lived_trades"])
    if limit_trades:
        lived = lived.head(int(limit_trades)).copy()

    cand_df = pd.DataFrame(candidates) if candidates else pd.DataFrame()
    join = lived.merge(cand_df, how="left", on="position_id", suffixes=("", "_cand")) if len(cand_df) else lived.copy()

    policy_stats = _policy_counterfactuals(lived=lived, candidates=candidates, decisions=decisions)
    key_policy_stats = {p: policy_stats[p] for p in KEY_POLICIES if p in policy_stats}

    join_path = paths["reports"] / "lived_eqcorr_join_multi_tf.parquet"
    join.to_parquet(join_path, index=False)

    baseline = policy_stats.get("BASELINE_ALL_ELIGIBLE", {}).get("executed") or _bucket_stats(
        lived["net_pnl_usd"].astype(float).tolist()
    )

    summary = {
        "stage": "ETLL_SHADOW_EQCORR_MULTI_TF",
        "status": "EQCORR_MULTI_TF_DONE",
        "timeframe": "MULTI",
        "timeframes": ["M15", "M30", "H1", "H4"],
        "epoch_id": epoch,
        "polls": polls,
        "candidates": len(candidates),
        "policy_decisions": len(decisions),
        "lived_trades": int(len(lived)),
        "joined_with_candidate": int(join["candidate_id"].notna().sum()) if "candidate_id" in join.columns else 0,
        "overall_baseline": baseline,
        "policy_counterfactuals": key_policy_stats,
        "all_policy_ids": sorted(policy_stats.keys()),
        "artifacts": {
            "shadow_eqcorr": str(eq_dir),
            "join": str(join_path),
            "lived_trades": str(paths["lived_trades"]),
        },
        "enrichment_note": "M15 pack context symlinked; partial Stage-2 planes vs live cognition",
        "external_trades_used": False,
    }
    out_json = paths["reports"] / "shadow_eqcorr_summary_multi_tf.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-adapt", action="store_true")
    parser.add_argument("--limit-trades", type=int, default=None)
    parser.add_argument("--no-fresh", action="store_true")
    parser.add_argument("--max-idle-polls", type=int, default=5)
    args = parser.parse_args()
    summary = run_multi_tf_eqcorr(
        skip_adapt=args.skip_adapt,
        limit_trades=args.limit_trades,
        fresh=not args.no_fresh,
        max_idle_polls=args.max_idle_polls,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
