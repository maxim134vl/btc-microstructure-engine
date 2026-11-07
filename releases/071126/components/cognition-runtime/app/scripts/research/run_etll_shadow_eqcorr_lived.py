#!/usr/bin/env python3
"""ETLL: Shadow EQCORR batch on adapted lived paper books.

Produces first candidates under pack shadow_lab. External trades not used.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import (  # noqa: E402
    EPOCH_ID,
    adapt_lived_books_to_jsonl,
    ensure_lab_dirs,
    pack_paths,
)
from btc_ml.trading.shadow_economic_correlation.engine import (  # noqa: E402
    ShadowEconomicCorrelationEngine,
)

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--skip-adapt", action="store_true")
    parser.add_argument("--limit-trades", type=int, default=None)
    parser.add_argument("--max-polls", type=int, default=3, help="poll_once iterations (idempotent after first)")
    args = parser.parse_args()

    paths = pack_paths(args.pack_dir)
    ensure_lab_dirs(paths)
    if not args.skip_adapt:
        adapt_lived_books_to_jsonl(pack_dir=args.pack_dir, limit_trades=args.limit_trades)

    engine = ShadowEconomicCorrelationEngine(
        repo=paths["paper_repo"],
        epoch_id=EPOCH_ID,
        strict_epoch=False,
        shadow_dir=paths["shadow_eqcorr"],
    )
    polls = []
    for _ in range(max(1, int(args.max_polls))):
        polls.append(engine.poll_once())

    snap_path = paths["shadow_eqcorr"] / "candidate_snapshots.jsonl"
    dec_path = paths["shadow_eqcorr"] / "policy_decisions.jsonl"
    # store may nest under different names — list dir
    eq_files = {p.name: p for p in paths["shadow_eqcorr"].rglob("*.jsonl")}
    candidates = _read_jsonl(eq_files.get("candidate_snapshots.jsonl", snap_path))
    decisions = _read_jsonl(eq_files.get("policy_decisions.jsonl", dec_path))

    lived = pd.read_parquet(paths["lived_trades"])
    if args.limit_trades:
        lived = lived.head(int(args.limit_trades)).copy()

    # Join candidates to lived by position_id
    cand_df = pd.DataFrame(candidates) if candidates else pd.DataFrame()
    if len(cand_df) and "position_id" in cand_df.columns:
        join = lived.merge(
            cand_df,
            how="left",
            left_on="position_id",
            right_on="position_id",
            suffixes=("", "_cand"),
        )
    else:
        join = lived.copy()
        join["candidate_id"] = None

    # Aggregate decision action per candidate — prefer entry-time non-null actions.
    # Focus primary label on BASELINE_ALL_ELIGIBLE; keep policy map for report.
    dec_df = pd.DataFrame(decisions) if decisions else pd.DataFrame()
    baseline_by_cand: dict[str, str] = {}
    any_by_cand: dict[str, str] = {}
    policy_matrix: dict[str, dict[str, str]] = {}
    if len(dec_df) and "candidate_id" in dec_df.columns:
        for _, row in dec_df.iterrows():
            cid = str(row.get("candidate_id") or "")
            action = row.get("action")
            if action is None or (isinstance(action, float) and pd.isna(action)):
                continue
            action_s = str(action)
            if not cid or not action_s or action_s.lower() == "none":
                continue
            policy = str(row.get("policy_id") or "")
            policy_matrix.setdefault(cid, {})[policy] = action_s
            any_by_cand[cid] = action_s
            if policy == "BASELINE_ALL_ELIGIBLE":
                baseline_by_cand[cid] = action_s

    if "candidate_id" in join.columns:
        join["eqcorr_action"] = join["candidate_id"].map(
            lambda x: baseline_by_cand.get(str(x)) or any_by_cand.get(str(x)) if pd.notna(x) else None
        )
        join["eqcorr_candidate_id"] = join["candidate_id"]
    else:
        join["eqcorr_action"] = None
        join["eqcorr_candidate_id"] = None

    join_path = paths["reports"] / "lived_eqcorr_join.parquet"
    join.to_parquet(join_path, index=False)

    def _bucket_stats(frame: pd.DataFrame) -> dict:
        if not len(frame):
            return {"n": 0}
        net = pd.to_numeric(frame.get("net_pnl_usd"), errors="coerce")
        wins = net[net > 0]
        losses = net[net < 0]
        return {
            "n": int(len(frame)),
            "wr": float((net > 0).mean()) if len(net) else None,
            "net_pnl_usd": float(net.fillna(0).sum()),
            "avg_pnl_usd": float(net.mean()) if len(net) else None,
            "wins": int(len(wins)),
            "losses": int(len(losses)),
        }

    by_action = {}
    if "eqcorr_action" in join.columns:
        for action, g in join.groupby(join["eqcorr_action"].fillna("NO_DECISION").astype(str)):
            by_action[action] = _bucket_stats(g)

    # Policy disagreement vs baseline (how often non-baseline blocks)
    block_rates = {}
    if policy_matrix:
        for policy in sorted({p for m in policy_matrix.values() for p in m}):
            vals = [m.get(policy) for m in policy_matrix.values() if policy in m]
            if not vals:
                continue
            block_rates[policy] = {
                "n": len(vals),
                "block_rate": float(sum(1 for a in vals if "BLOCK" in str(a).upper()) / len(vals)),
                "execute_full_rate": float(sum(1 for a in vals if a == "EXECUTE_FULL") / len(vals)),
                "execute_reduced_rate": float(sum(1 for a in vals if a == "EXECUTE_REDUCED") / len(vals)),
            }

    summary = {
        "stage": "ETLL_SHADOW_EQCORR_LIVED",
        "status": "EQCORR_BATCH_DONE",
        "epoch_id": EPOCH_ID,
        "polls": polls,
        "candidates": len(candidates),
        "policy_decisions": len(decisions),
        "lived_trades": int(len(lived)),
        "joined_with_candidate": int(join["eqcorr_candidate_id"].notna().sum())
        if "eqcorr_candidate_id" in join.columns
        else 0,
        "by_eqcorr_action_baseline": by_action,
        "policy_action_rates": block_rates,
        "overall": _bucket_stats(lived),
        "artifacts": {
            "shadow_eqcorr": str(paths["shadow_eqcorr"]),
            "join": str(join_path),
            "eqcorr_jsonl": sorted(eq_files.keys()),
        },
        "enrichment_note": "Stage-2 live cognition mostly FIELD_NOT_AVAILABLE; core policy from books only",
        "external_trades_used": False,
    }
    (paths["reports"] / "shadow_eqcorr_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
