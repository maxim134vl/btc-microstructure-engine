#!/usr/bin/env python3
"""S4.1 candidate replay: manager + four independent traders on candidate paths.

Point-in-time only: at every evaluation instant the manager and traders see
exactly the bars that were already complete. Production paths are never touched.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import proofs  # noqa: E402
from btc_ml.trading.command_bus import CommandBus, CommandBusPaths  # noqa: E402
from btc_ml.trading.paper_core import closed_trade_economics, core_fingerprint  # noqa: E402
from btc_ml.trading.paper_trader_engine import PaperTraderEngine  # noqa: E402
from btc_ml.trading.timeframe_manager import SUPPORTED_TIMEFRAMES, TimeframeManager, load_feed  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import load_sources  # noqa: E402
from btc_ml.trading.timeframe_trader import TimeframeTrader  # noqa: E402
from btc_ml.trading.trader_book import TraderBook  # noqa: E402

RESEARCH = ROOT / "data" / "research"
AVAILABILITY_MEMORY = ROOT / "data" / "cognition" / "multi_timeframe_availability_memory.parquet"

REPLAY_COLUMNS = [
    "cycle_index",
    "evaluation_timestamp",
    "manager_cycle_id",
    "timeframe",
    "availability_status",
    "source_bar_close",
    "timeframe_state",
    "timeframe_direction",
    "lifecycle_episode_id",
    "lifecycle_phase",
    "intent",
    "action_allowed",
    "reason_codes",
    "requested_risk_usd",
    "approved_risk_usd",
    "portfolio_open_risk_usd",
    "trader_result",
    "trader_reason",
    "position_id",
    "position_direction",
    "position_status",
    "entry_price",
    "fill_timestamp",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "open_risk_usd",
    "gross_open_risk_usd",
    "open_positions_portfolio",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def reset_candidate_state() -> list[str]:
    removed: list[str] = []
    paths = CommandBusPaths.candidate()
    for path in (paths.memory, paths.latest, paths.manager_state, paths.portfolio_summary):
        for target in (path, path.with_suffix(path.suffix + ".meta.json")):
            if target.exists():
                target.unlink()
                removed.append(str(target.relative_to(ROOT)))
    for tf in SUPPORTED_TIMEFRAMES:
        book = TraderBook.candidate(tf)
        if book.root.exists():
            shutil.rmtree(book.root)
            removed.append(str(book.root.relative_to(ROOT)))
    return removed


def evaluation_timestamps(*, limit: int | None) -> list[pd.Timestamp]:
    frame = pd.read_parquet(AVAILABILITY_MEMORY, columns=["evaluation_timestamp", "timeframe"])
    m15 = frame[frame["timeframe"].astype(str).str.upper() == "M15"]
    stamps = pd.to_datetime(m15["evaluation_timestamp"], utc=True, errors="coerce").dropna()
    ordered = sorted(set(stamps.tolist()))
    return ordered if not limit else ordered[-limit:]


def run_replay(*, limit: int | None, reset: bool) -> dict[str, Any]:
    removed = reset_candidate_state() if reset else []
    feed = load_feed()
    sources = load_sources()
    manager = TimeframeManager.candidate()
    traders = {tf: TimeframeTrader.candidate(tf) for tf in SUPPORTED_TIMEFRAMES}
    stamps = evaluation_timestamps(limit=limit)

    rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    opposite_natural: list[dict[str, Any]] = []
    unclosed_bar_joins = 0
    future_joins = 0
    aggregate_breaches = 0

    for index, evaluation in enumerate(stamps):
        visible = proofs.visible_feed(feed, evaluation)
        if not len(visible):
            continue
        cycle = manager.run_cycle(evaluation_timestamp=evaluation, sources=sources, feed=visible, persist=True)
        commands = {cmd["timeframe"]: cmd for cmd in cycle["commands"]}
        for tf, command in commands.items():
            bar_close = command.get("source_bar_close")
            if bar_close and pd.Timestamp(bar_close) > pd.Timestamp(evaluation):
                unclosed_bar_joins += 1

        outcomes: dict[str, dict[str, Any]] = {}
        for tf in SUPPORTED_TIMEFRAMES:
            result = traders[tf].run_once(feed=visible)
            for outcome in result["outcomes"]:
                outcomes[tf] = outcome
                fill_ts = outcome.get("fill_timestamp")
                command_eval = outcome.get("evaluation_timestamp")
                if fill_ts and command_eval and pd.Timestamp(fill_ts) <= pd.Timestamp(command_eval):
                    future_joins += 1

        views = {tf: PaperTraderEngine(TraderBook.candidate(tf)).snapshot() for tf in SUPPORTED_TIMEFRAMES}
        gross_risk = sum(abs(float(v.get("open_risk_usd") or 0.0)) for v in views.values())
        open_count = sum(1 for v in views.values() if v.get("open_position"))
        if gross_risk > manager.risk.portfolio_max_risk_usd + 1e-9:
            aggregate_breaches += 1

        directions = {
            tf: str((views[tf].get("open_position") or {}).get("direction") or "").upper()
            for tf in SUPPORTED_TIMEFRAMES
        }
        if "LONG" in directions.values() and "SHORT" in directions.values():
            opposite_natural.append(
                {
                    "evaluation_timestamp": str(evaluation),
                    "directions": {tf: direction for tf, direction in directions.items() if direction},
                }
            )

        for tf in SUPPORTED_TIMEFRAMES:
            command = commands.get(tf, {})
            outcome = outcomes.get(tf, {})
            position = views[tf].get("open_position") or {}
            rows.append(
                {
                    "cycle_index": index,
                    "evaluation_timestamp": str(evaluation),
                    "manager_cycle_id": cycle["manager_cycle_id"],
                    "timeframe": tf,
                    "availability_status": command.get("availability_status"),
                    "source_bar_close": command.get("source_bar_close"),
                    "timeframe_state": command.get("timeframe_state"),
                    "timeframe_direction": command.get("timeframe_direction"),
                    "lifecycle_episode_id": command.get("lifecycle_episode_id"),
                    "lifecycle_phase": command.get("lifecycle_phase"),
                    "intent": command.get("intent"),
                    "action_allowed": command.get("action_allowed"),
                    "reason_codes": command.get("reason_codes"),
                    "requested_risk_usd": command.get("requested_risk_usd"),
                    "approved_risk_usd": command.get("approved_risk_usd"),
                    "portfolio_open_risk_usd": command.get("portfolio_open_risk_usd"),
                    "trader_result": outcome.get("result"),
                    "trader_reason": outcome.get("reason"),
                    "position_id": position.get("position_id"),
                    "position_direction": position.get("direction"),
                    "position_status": position.get("status"),
                    "entry_price": position.get("entry_price"),
                    "fill_timestamp": outcome.get("fill_timestamp"),
                    "realized_pnl_usd": views[tf].get("realized_pnl_usd"),
                    "unrealized_pnl_usd": views[tf].get("unrealized_pnl_usd"),
                    "open_risk_usd": views[tf].get("open_risk_usd"),
                    "gross_open_risk_usd": gross_risk,
                    "open_positions_portfolio": open_count,
                }
            )
            risk_rows.append(
                {
                    "evaluation_timestamp": str(evaluation),
                    "timeframe": tf,
                    "trader_open_risk_usd": views[tf].get("open_risk_usd"),
                    "trader_max_risk_usd": manager.risk.trader_budget(tf),
                    "trader_within_limit": float(views[tf].get("open_risk_usd") or 0.0)
                    <= manager.risk.trader_budget(tf) + 1e-9,
                    "gross_open_risk_usd": gross_risk,
                    "portfolio_max_risk_usd": manager.risk.portfolio_max_risk_usd,
                    "portfolio_within_limit": gross_risk <= manager.risk.portfolio_max_risk_usd + 1e-9,
                    "risk_aggregation": "GROSS_NO_NETTING",
                }
            )

    replay_frame = pd.DataFrame(rows, columns=REPLAY_COLUMNS)
    replay_path = RESEARCH / "s4_1_candidate_replay.parquet"
    replay_frame.to_parquet(replay_path, index=False)

    risk_path = RESEARCH / "s4_1_risk_reconciliation.csv"
    with risk_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(risk_rows[0].keys()) if risk_rows else ["evaluation_timestamp"])
        writer.writeheader()
        writer.writerows(risk_rows)

    integrity = candidate_integrity()
    pnl_rows = pnl_reconciliation()
    pnl_path = RESEARCH / "s4_1_pnl_reconciliation.csv"
    pnl_fields = [
        "timeframe",
        "trade_id",
        "side",
        "entry_price",
        "exit_price",
        "quantity",
        "stored_gross_pnl_usd",
        "recomputed_gross_pnl_usd",
        "stored_net_pnl_usd",
        "recomputed_net_pnl_usd",
        "stored_fees_usd",
        "recomputed_fees_usd",
        "stored_slippage_usd",
        "recomputed_slippage_usd",
        "match",
    ]
    with pnl_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=pnl_fields)
        writer.writeheader()
        writer.writerows(pnl_rows)

    bus = CommandBus(CommandBusPaths.candidate())
    commands_frame = bus.frame()
    duplicate_commands = (
        int(len(commands_frame) - commands_frame["command_id"].astype(str).nunique()) if len(commands_frame) else 0
    )
    intent_counts = (
        commands_frame.groupby(["timeframe", "intent"]).size().unstack(fill_value=0).to_dict()
        if len(commands_frame)
        else {}
    )

    summary = {
        "generated_at": _now(),
        "stage": "S4_1_CANDIDATE_REPLAY",
        "cycles": len(stamps),
        "replay_rows": int(len(replay_frame)),
        "reset_removed": removed,
        "window": {
            "first_evaluation_timestamp": str(stamps[0]) if stamps else None,
            "last_evaluation_timestamp": str(stamps[-1]) if stamps else None,
        },
        "shared_execution_core": core_fingerprint(),
        "command_bus": {
            "path": str(CommandBusPaths.candidate().memory.relative_to(ROOT)),
            "rows": int(len(commands_frame)),
            "duplicate_commands": duplicate_commands,
            "intent_counts_by_timeframe": intent_counts,
        },
        "invariants": {
            "future_joins": future_joins,
            "unclosed_bar_joins": unclosed_bar_joins,
            "duplicate_commands": duplicate_commands,
            "aggregate_risk_breaches": aggregate_breaches,
            **integrity,
        },
        "natural_opposite_position_cycles": len(opposite_natural),
        "natural_opposite_examples": opposite_natural[:10],
        "pnl_reconciliation": {
            "rows": len(pnl_rows),
            "mismatches": sum(1 for row in pnl_rows if not row["match"]),
            "path": str(pnl_path.relative_to(ROOT)),
        },
        "artifacts": {
            "replay_parquet": str(replay_path.relative_to(ROOT)),
            "risk_csv": str(risk_path.relative_to(ROOT)),
            "pnl_csv": str(pnl_path.relative_to(ROOT)),
            "portfolio_summary": str(CommandBusPaths.candidate().portfolio_summary.relative_to(ROOT)),
        },
        "paper_only": True,
        "execution_enabled": False,
        "exchange_calls": 0,
    }
    return summary


def candidate_integrity() -> dict[str, Any]:
    duplicate_signals = 0
    duplicate_orders = 0
    duplicate_fills = 0
    duplicate_trades = 0
    duplicate_positions = 0
    cross_trader_state_writes = 0
    multi_open_positions = 0
    per_timeframe: dict[str, Any] = {}
    for tf in SUPPORTED_TIMEFRAMES:
        book = TraderBook.candidate(tf)
        signals = book.signals_frame()
        orders = book.orders_frame()
        fills = book.fills_frame()
        positions = book.positions_frame()
        trades = book.trades_frame()
        duplicate_signals += int(len(signals) - signals["signal_id"].astype(str).nunique()) if len(signals) else 0
        duplicate_orders += int(len(orders) - orders["paper_order_id"].astype(str).nunique()) if len(orders) else 0
        duplicate_fills += int(len(fills) - fills["paper_trade_id"].astype(str).nunique()) if len(fills) else 0
        duplicate_trades += int(len(trades) - trades["trade_id"].astype(str).nunique()) if len(trades) else 0
        duplicate_positions += (
            int(len(positions) - positions["position_id"].astype(str).nunique()) if len(positions) else 0
        )
        for frame in (signals, orders, fills, positions):
            if len(frame) and "timeframe" in frame.columns:
                cross_trader_state_writes += int((frame["timeframe"].astype(str).str.upper() != tf).sum())
        if len(trades) and "timeframe" in trades.columns:
            cross_trader_state_writes += int((trades["timeframe"].astype(str).str.upper() != tf).sum())
        open_rows = (
            int((positions["status"].astype(str).str.upper() == "OPEN").sum()) if len(positions) else 0
        )
        if open_rows > 1:
            multi_open_positions += 1
        per_timeframe[tf] = {
            "signals": int(len(signals)),
            "orders": int(len(orders)),
            "fills": int(len(fills)),
            "positions": int(len(positions)),
            "open_positions": open_rows,
            "closed_trades": int(len(trades)),
        }
    return {
        "duplicate_signals": duplicate_signals,
        "duplicate_orders": duplicate_orders,
        "duplicate_fills": duplicate_fills,
        "duplicate_trades": duplicate_trades,
        "duplicate_positions": duplicate_positions,
        "cross_trader_state_writes": cross_trader_state_writes,
        "traders_with_multiple_open_positions": multi_open_positions,
        "per_timeframe": per_timeframe,
    }


def pnl_reconciliation() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tf in SUPPORTED_TIMEFRAMES:
        trades = TraderBook.candidate(tf).trades_frame()
        for _, trade in trades.iterrows():
            expected = closed_trade_economics(
                side=trade["side"],
                entry_price=trade["entry_price"],
                exit_price=trade["exit_price"],
                position_size_btc=trade["quantity"],
                stop_loss_price=trade["stop_loss_price"],
                take_profit_price=trade["take_profit_price"],
                risk_amount_usd=trade["risk_amount_usd"],
                exit_reason=trade["exit_reason"],
                exit_execution_source="live_market_feed_completed_bar_close",
            )
            match = all(
                abs(float(trade[stored]) - float(expected[key])) < 1e-6
                for stored, key in (
                    ("gross_pnl_usd", "gross_pnl_usd"),
                    ("net_pnl_usd", "net_pnl_usd"),
                    ("fees_usd", "fees_usd"),
                    ("slippage_usd", "slippage_usd"),
                )
            )
            rows.append(
                {
                    "timeframe": tf,
                    "trade_id": trade["trade_id"],
                    "side": trade["side"],
                    "entry_price": trade["entry_price"],
                    "exit_price": trade["exit_price"],
                    "quantity": trade["quantity"],
                    "stored_gross_pnl_usd": trade["gross_pnl_usd"],
                    "recomputed_gross_pnl_usd": expected["gross_pnl_usd"],
                    "stored_net_pnl_usd": trade["net_pnl_usd"],
                    "recomputed_net_pnl_usd": expected["net_pnl_usd"],
                    "stored_fees_usd": trade["fees_usd"],
                    "recomputed_fees_usd": expected["fees_usd"],
                    "stored_slippage_usd": trade["slippage_usd"],
                    "recomputed_slippage_usd": expected["slippage_usd"],
                    "match": match,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only replay the last N M15 evaluation instants")
    parser.add_argument("--no-reset", action="store_true", help="append to existing candidate books")
    args = parser.parse_args(argv)

    RESEARCH.mkdir(parents=True, exist_ok=True)
    summary = run_replay(limit=args.limit, reset=not args.no_reset)

    proof_root = RESEARCH / "s4_1_proof_workspace"
    if proof_root.exists():
        shutil.rmtree(proof_root)
    opposite = proofs.run_opposite_positions_proof(proof_root / "opposite")
    restart = proofs.run_restart_proof(proof_root / "restart")
    risk = proofs.run_portfolio_risk_proof()
    fill = proofs.run_fill_contract_proof(proof_root / "fill")
    pnl = proofs.run_pnl_proof(proof_root / "pnl")

    (RESEARCH / "s4_1_opposite_positions_proof.json").write_text(
        json.dumps(opposite, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (RESEARCH / "s4_1_restart_proof.json").write_text(
        json.dumps({"restart": restart, "portfolio_risk": risk, "fill_contract": fill, "pnl": pnl}, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )

    invariants = summary["invariants"]
    gates = {
        "candidate_replay_passed": all(
            invariants[key] == 0
            for key in (
                "future_joins",
                "unclosed_bar_joins",
                "duplicate_commands",
                "duplicate_signals",
                "duplicate_orders",
                "duplicate_fills",
                "duplicate_trades",
                "duplicate_positions",
                "cross_trader_state_writes",
                "traders_with_multiple_open_positions",
                "aggregate_risk_breaches",
            )
        ),
        "opposite_positions_test_passed": bool(opposite["passed"]),
        "restart_isolation_passed": bool(restart["passed"]),
        "portfolio_risk_passed": bool(risk["passed"]),
        "point_in_time_fill_passed": bool(fill["passed"]),
        "pnl_reconciliation_passed": bool(pnl["passed"]) and summary["pnl_reconciliation"]["mismatches"] == 0,
        "exchange_calls": 0,
    }
    summary["gates"] = gates
    summary["proofs"] = {
        "opposite_positions": str((RESEARCH / "s4_1_opposite_positions_proof.json").relative_to(ROOT)),
        "restart_and_risk": str((RESEARCH / "s4_1_restart_proof.json").relative_to(ROOT)),
    }
    summary["candidate_status"] = (
        "S4_MANAGER_TRADER_ARCHITECTURE_CANDIDATE_READY"
        if all(v is True or v == 0 for v in gates.values())
        else "S4_MANAGER_TRADER_ARCHITECTURE_BLOCKED"
    )
    (RESEARCH / "s4_1_candidate_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if proof_root.exists():
        shutil.rmtree(proof_root)

    print(
        json.dumps(
            {
                "candidate_status": summary["candidate_status"],
                "cycles": summary["cycles"],
                "invariants": {k: v for k, v in invariants.items() if k != "per_timeframe"},
                "per_timeframe": invariants["per_timeframe"],
                "gates": gates,
                "natural_opposite_position_cycles": summary["natural_opposite_position_cycles"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
