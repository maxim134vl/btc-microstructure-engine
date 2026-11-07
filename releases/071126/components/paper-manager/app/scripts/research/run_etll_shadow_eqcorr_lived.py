#!/usr/bin/env python3
"""ETLL: Shadow EQCORR batch on adapted lived paper books (any TF).

Produces candidates under pack lived_replay/shadow_lab. External trades not used.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import (  # noqa: E402
    adapt_lived_books_to_jsonl,
    default_pack_dir,
    ensure_lab_dirs,
    epoch_id_for,
    link_pack_cognition_for_eqcorr,
    pack_paths,
)
from btc_ml.trading.shadow_economic_correlation.engine import (  # noqa: E402
    ShadowEconomicCorrelationEngine,
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


def run_eqcorr(
    *,
    pack_dir: Path,
    timeframe: str,
    skip_adapt: bool = False,
    limit_trades: int | None = None,
    fresh: bool = True,
    max_idle_polls: int = 5,
) -> dict:
    tf = str(timeframe).upper()
    epoch = epoch_id_for(tf)
    paths = pack_paths(pack_dir, timeframe=tf)
    ensure_lab_dirs(paths)

    if fresh and paths["shadow_eqcorr"].exists():
        shutil.rmtree(paths["shadow_eqcorr"])
        paths["shadow_eqcorr"].mkdir(parents=True, exist_ok=True)

    if not skip_adapt:
        adapt_lived_books_to_jsonl(pack_dir=pack_dir, timeframe=tf, limit_trades=limit_trades)

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
        polls.append(poll)
        if poll.get("entries", 0) == 0 and poll.get("closes", 0) == 0 and poll.get("enrichments", 0) == 0:
            idle_streak += 1
        else:
            idle_streak = 0

    snap_path = paths["shadow_eqcorr"] / "candidate_snapshots.jsonl"
    dec_path = paths["shadow_eqcorr"] / "policy_decisions.jsonl"
    eq_files = {p.name: p for p in paths["shadow_eqcorr"].rglob("*.jsonl")}
    candidates = _read_jsonl(eq_files.get("candidate_snapshots.jsonl", snap_path))
    decisions = _read_jsonl(eq_files.get("policy_decisions.jsonl", dec_path))

    lived = pd.read_parquet(paths["lived_trades"])
    if limit_trades:
        lived = lived.head(int(limit_trades)).copy()

    cand_df = pd.DataFrame(candidates) if candidates else pd.DataFrame()
    if len(cand_df) and "position_id" in cand_df.columns:
        join = lived.merge(cand_df, how="left", on="position_id", suffixes=("", "_cand"))
    else:
        join = lived.copy()
        join["candidate_id"] = None

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

    join_path = paths["reports"] / f"lived_eqcorr_join_{tf.lower()}.parquet"
    join.to_parquet(join_path, index=False)
    # legacy alias for M15
    if tf == "M15":
        join.to_parquet(paths["reports"] / "lived_eqcorr_join.parquet", index=False)

    by_action = {}
    if "eqcorr_action" in join.columns:
        for action, g in join.groupby(join["eqcorr_action"].fillna("NO_DECISION").astype(str)):
            by_action[action] = _bucket_stats(g)

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

    # Counterfactual: baseline EXECUTE_FULL only
    execute_mask = join["eqcorr_action"].astype(str).isin(["EXECUTE_FULL", "EXECUTE_REDUCED"])
    filtered = join[execute_mask | join["eqcorr_action"].isna()] if "eqcorr_action" in join.columns else join

    summary = {
        "stage": "ETLL_SHADOW_EQCORR_LIVED",
        "status": "EQCORR_BATCH_DONE",
        "timeframe": tf,
        "epoch_id": epoch,
        "polls": polls,
        "candidates": len(candidates),
        "policy_decisions": len(decisions),
        "lived_trades": int(len(lived)),
        "joined_with_candidate": int(join["eqcorr_candidate_id"].notna().sum())
        if "eqcorr_candidate_id" in join.columns
        else 0,
        "by_eqcorr_action_baseline": by_action,
        "policy_action_rates": block_rates,
        "overall_baseline": _bucket_stats(lived),
        "execute_full_or_reduced_subset": _bucket_stats(filtered),
        "artifacts": {
            "shadow_eqcorr": str(paths["shadow_eqcorr"]),
            "join": str(join_path),
            "eqcorr_jsonl": sorted(eq_files.keys()),
        },
        "enrichment_note": "Pack context symlinked; partial Stage-2 planes vs live cognition",
        "external_trades_used": False,
    }
    out_json = paths["reports"] / f"shadow_eqcorr_summary_{tf.lower()}.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if tf == "M15":
        (paths["reports"] / "shadow_eqcorr_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", type=str, default="M15", help="M15, M30, H1, H4")
    parser.add_argument("--pack-dir", type=Path, default=None)
    parser.add_argument("--skip-adapt", action="store_true")
    parser.add_argument("--limit-trades", type=int, default=None)
    parser.add_argument("--no-fresh", action="store_true", help="Do not wipe prior eqcorr epoch dir")
    parser.add_argument("--max-idle-polls", type=int, default=5)
    args = parser.parse_args()
    tf = str(args.timeframe).upper()
    pack_dir = args.pack_dir or default_pack_dir(tf)
    summary = run_eqcorr(
        pack_dir=pack_dir,
        timeframe=tf,
        skip_adapt=args.skip_adapt,
        limit_trades=args.limit_trades,
        fresh=not args.no_fresh,
        max_idle_polls=args.max_idle_polls,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
