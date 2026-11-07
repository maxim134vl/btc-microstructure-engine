#!/usr/bin/env python3
"""ETLL STP_BE33 filter-pass pilot on lived M15 trades + exact aggTrade path.

Replays BE33 policy semantics (1/3 partial @ 33% to TP, economic BE stop) on
exact aggTrade paths for the June pilot universe. Writes research artifacts only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics  # noqa: E402
from btc_ml.trading.shadow_structural_protection.be33 import (  # noqa: E402
    partial_trigger_price,
    solve_economic_break_even,
)
from btc_ml.trading.shadow_structural_protection.timeutil import parse_ts  # noqa: E402
from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades  # noqa: E402

DEFAULT_UNIVERSE = (
    ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/pilot_trade_universe.json"
)
DEFAULT_TICK_REPO = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/stp2_pilot/tick_pack_202606/repo"
)
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/stp_be33_pilot"
DEFAULT_MANIFEST = (
    ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/tick_pack_manifest.json"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts_iso(ts) -> str:
    if hasattr(ts, "isoformat"):
        return ts.isoformat().replace("+00:00", "Z")
    return str(ts)


def _simulate_trade(*, trade: dict[str, Any], path: pd.DataFrame, cfg) -> dict[str, Any]:
    side = str(trade["side"]).upper()
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss_price"])
    take = float(trade["take_profit_price"])
    qty = float(trade["quantity"])
    risk = abs(entry - stop) * qty
    if risk <= 0:
        risk = float(trade.get("risk_amount_usd") or 1000.0)
    partial_qty = qty / 3.0
    remain_qty = qty - partial_qty
    trigger = partial_trigger_price(side=side, entry_price=entry, take_price=take)

    can_pnl = float(trade["net_pnl_usd"])
    can_exit = float(trade["exit_price"])
    can_ts = str(trade["exit_ts"])
    can_reason = str(trade.get("exit_reason") or "CANONICAL_EXIT")

    row: dict[str, Any] = {
        "trade_id": trade["trade_id"],
        "position_id": trade.get("position_id"),
        "side": side,
        "entry_ts": trade["entry_ts"],
        "entry_price": entry,
        "quantity": qty,
        "partial_trigger_price": trigger,
        "canonical_net_pnl_usd": can_pnl,
        "canonical_exit_ts": can_ts,
        "canonical_exit_price": can_exit,
        "canonical_exit_reason": can_reason,
        "fidelity": "EXACT_AGG_TRADE",
        "evaluated": True,
        "skip_reason": None,
        "partial_taken": False,
        "final_exit_reason": None,
        "total_net_pnl_usd": None,
        "net_difference_vs_canonical_usd": None,
        "path_rows": int(len(path)) if path is not None else 0,
    }
    if path is None or path.empty:
        row.update(
            {
                "evaluated": False,
                "skip_reason": "NO_AGG_PATH",
                "total_net_pnl_usd": can_pnl,
                "net_difference_vs_canonical_usd": 0.0,
                "final_exit_reason": "CANONICAL_EXIT_NO_PATH",
            }
        )
        return row

    # Fast path: numpy scan (iterrows is ~100x slower on multi-100k aggTrades).
    can_ts_parsed = parse_ts(can_ts)
    prices = path["price"].to_numpy(dtype="float64", copy=False)
    ts_vals = pd.to_datetime(path["_ts"], utc=True)
    if can_ts_parsed is not None:
        cutoff = pd.Timestamp(can_ts_parsed)
        mask = ts_vals < cutoff
        prices = prices[mask.to_numpy()]
        ts_vals = ts_vals[mask]

    shadow_stop = stop
    partial_taken = False
    partial_net = 0.0
    partial_ts = None
    be_price = None
    n = int(len(prices))
    i = 0
    while i < n:
        price = float(prices[i])
        if side == "LONG":
            hit_stop = price <= shadow_stop
            hit_trigger = (not partial_taken) and price >= trigger
            hit_tp = price >= take
        else:
            hit_stop = price >= shadow_stop
            hit_trigger = (not partial_taken) and price <= trigger
            hit_tp = price <= take

        if hit_stop:
            ts_s = _ts_iso(ts_vals.iloc[i] if hasattr(ts_vals, "iloc") else ts_vals[i])
            reason = "BE_STOP" if partial_taken else "SL"
            qty_rem = remain_qty if partial_taken else qty
            econ = closed_trade_economics(
                cfg=cfg,
                side=side,
                entry_price=entry,
                exit_price=shadow_stop,
                quantity=qty_rem,
                risk_amount_usd=risk * (qty_rem / qty),
                exit_reason="SL" if reason == "BE_STOP" else reason,
            )
            total = partial_net + float(econ["net_pnl_usd"])
            row.update(
                {
                    "partial_taken": partial_taken,
                    "partial_trigger_timestamp": partial_ts,
                    "economic_break_even_price": be_price,
                    "final_exit_reason": reason,
                    "final_exit_price": shadow_stop,
                    "final_exit_ts": ts_s,
                    "total_net_pnl_usd": total,
                    "net_difference_vs_canonical_usd": total - can_pnl,
                }
            )
            return row
        if hit_trigger:
            ts_s = _ts_iso(ts_vals.iloc[i] if hasattr(ts_vals, "iloc") else ts_vals[i])
            pe = closed_trade_economics(
                cfg=cfg,
                side=side,
                entry_price=entry,
                exit_price=trigger,
                quantity=partial_qty,
                risk_amount_usd=risk * (partial_qty / qty),
                exit_reason="PARTIAL_TAKE",
            )
            remain_risk = risk * (remain_qty / qty)
            be_price, _ = solve_economic_break_even(
                cfg=cfg,
                side=side,
                entry_price=entry,
                quantity=remain_qty,
                risk_amount_usd=remain_risk,
            )
            partial_taken = True
            partial_net = float(pe["net_pnl_usd"])
            partial_ts = ts_s
            shadow_stop = float(be_price)
            i += 1
            continue
        if hit_tp:
            ts_s = _ts_iso(ts_vals.iloc[i] if hasattr(ts_vals, "iloc") else ts_vals[i])
            qty_rem = remain_qty if partial_taken else qty
            econ = closed_trade_economics(
                cfg=cfg,
                side=side,
                entry_price=entry,
                exit_price=take,
                quantity=qty_rem,
                risk_amount_usd=risk * (qty_rem / qty),
                exit_reason="TP",
            )
            total = partial_net + float(econ["net_pnl_usd"])
            row.update(
                {
                    "partial_taken": partial_taken,
                    "partial_trigger_timestamp": partial_ts,
                    "economic_break_even_price": be_price,
                    "final_exit_reason": "TP",
                    "final_exit_price": take,
                    "final_exit_ts": ts_s,
                    "total_net_pnl_usd": total,
                    "net_difference_vs_canonical_usd": total - can_pnl,
                }
            )
            return row
        i += 1

    # No BE33 terminal — canonical exit.
    if partial_taken:
        econ = closed_trade_economics(
            cfg=cfg,
            side=side,
            entry_price=entry,
            exit_price=can_exit,
            quantity=remain_qty,
            risk_amount_usd=risk * (remain_qty / qty),
            exit_reason="CANONICAL_EXIT",
        )
        total = partial_net + float(econ["net_pnl_usd"])
    else:
        total = can_pnl
    row.update(
        {
            "partial_taken": partial_taken,
            "partial_trigger_timestamp": partial_ts,
            "economic_break_even_price": be_price,
            "final_exit_reason": "CANONICAL_EXIT_BEFORE_PARTIAL"
            if not partial_taken
            else "CANONICAL_EXIT_AFTER_PARTIAL",
            "final_exit_price": can_exit,
            "final_exit_ts": can_ts,
            "total_net_pnl_usd": total,
            "net_difference_vs_canonical_usd": total - can_pnl,
        }
    )
    return row


def _summarize(rows: list[dict[str, Any]], *, n_lived: int, tick_cov: float, runtime: float, smoke: bool) -> dict[str, Any]:
    evaluated = [r for r in rows if r.get("evaluated")]
    diffs = [float(r["net_difference_vs_canonical_usd"]) for r in evaluated if r.get("net_difference_vs_canonical_usd") is not None]
    partial_n = sum(1 for r in evaluated if r.get("partial_taken"))
    gate_a = {
        "tick_coverage_hours_pct_ok": tick_cov >= 99.0,
        "evaluable_pct": round(100.0 * len(evaluated) / max(n_lived, 1), 4),
        "evaluable_pct_ok": (100.0 * len(evaluated) / max(n_lived, 1)) >= 90.0,
        "pass": tick_cov >= 99.0 and (100.0 * len(evaluated) / max(n_lived, 1)) >= 90.0,
    }
    return {
        "generated_at": _utc_now(),
        "stage": "STP_BE33_PILOT_SMOKE" if smoke else "STP_BE33_PILOT_202606",
        "status": "STP_BE33_PILOT_DONE",
        "shadow": "STP_BE33",
        "n_lived_trades_in_window": n_lived,
        "n_evaluated": len(evaluated),
        "n_skipped": n_lived - len(evaluated),
        "partial_trigger_rate": round(partial_n / max(len(evaluated), 1), 6),
        "be_stops_hit": sum(1 for r in evaluated if r.get("final_exit_reason") == "BE_STOP"),
        "tp_after_partial": sum(
            1 for r in evaluated if r.get("final_exit_reason") == "TP" and r.get("partial_taken")
        ),
        "canonical_exit_before_partial": sum(
            1 for r in evaluated if r.get("final_exit_reason") == "CANONICAL_EXIT_BEFORE_PARTIAL"
        ),
        "delta_net_pnl_usd_sum": round(sum(diffs), 6) if diffs else 0.0,
        "delta_net_pnl_usd_median": round(statistics.median(diffs), 6) if diffs else 0.0,
        "total_net_pnl_stp_be33": round(sum(float(r.get("total_net_pnl_usd") or 0) for r in evaluated), 6),
        "total_net_pnl_canonical_baseline": round(
            sum(float(r.get("canonical_net_pnl_usd") or 0) for r in evaluated), 6
        ),
        "exit_reason_counts": {
            k: sum(1 for r in evaluated if r.get("final_exit_reason") == k)
            for k in sorted({str(r.get("final_exit_reason")) for r in evaluated})
        },
        "external_trades_used": False,
        "fidelity": "EXACT_AGG_TRADE",
        "approximation_used": False,
        "tick_coverage_hours_pct": tick_cov,
        "runtime_seconds": round(runtime, 3),
        "gate_a": gate_a,
        "gate_verdict": "GO_REVIEW_GATE_B" if gate_a["pass"] else "NO_GO_FIX_GATE_A",
        "engine_note": (
            "Path simulator uses be33.partial_trigger_price / solve_economic_break_even "
            "and intrabar closed_trade_economics — same policy math as StpBe33Engine, "
            "without materializing multi-GB WAL JSONL on host RAM limits."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--tick-repo", type=Path, default=DEFAULT_TICK_REPO)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--paper-config-repo", type=Path, default=ROOT, help="Repo with intrabar_paper config")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    t0 = time.time()
    trades = list(json.loads(args.universe.read_text(encoding="utf-8")).get("trades") or [])
    if args.limit is not None:
        trades = trades[: int(args.limit)]
    tick_cov = 100.0
    if args.manifest.exists():
        tick_cov = float(json.loads(args.manifest.read_text(encoding="utf-8")).get("hour_coverage_pct") or 0)

    cfg = load_intrabar_paper_config(repo_root=args.paper_config_repo)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for i, trade in enumerate(trades, start=1):
        print(f"[{i}/{len(trades)}] {trade.get('trade_id')}", flush=True)
        entry_ts = parse_ts(trade["entry_ts"])
        exit_ts = parse_ts(trade["exit_ts"])
        path = (
            load_agg_trades(repo=args.tick_repo, start=entry_ts, end=exit_ts)
            if entry_ts and exit_ts
            else pd.DataFrame()
        )
        rows.append(_simulate_trade(trade=trade, path=path, cfg=cfg))

    runtime = time.time() - t0
    smoke = args.limit is not None and int(args.limit) < 97
    summary = _summarize(rows, n_lived=len(trades), tick_cov=tick_cov, runtime=runtime, smoke=smoke)
    tag = "smoke" if smoke else "202606"
    if rows:
        pd.DataFrame(rows).to_parquet(out_dir / f"stp_be33_pilot_{tag}_per_trade.parquet", index=False)
    (out_dir / f"stp_be33_pilot_{tag}_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    if not smoke:
        (out_dir / "stp_be33_pilot_202606_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: summary[k] for k in (
        "status", "n_evaluated", "partial_trigger_rate", "delta_net_pnl_usd_sum",
        "gate_a", "gate_verdict", "runtime_seconds",
    )}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
