#!/usr/bin/env python3
"""Recover the H1 TP-continuation that S4.1 issued while paper was hung."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics, resolve_risk_sizing
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger

EPOCH = "PER_TF_EQUITY_1PCT_V1_VPS_20260916_061956"
EPOCH_ROOT = Path("/app/data/trading/intrabar_paper") / EPOCH
BOOKS_ROOT = EPOCH_ROOT / "books"
CURSOR_PATH = EPOCH_ROOT / "s41_command_cursor.json"
OVERLAY = Path("/app/data/deployment/intrabar_paper_execution.overlay.json")
SOURCE_OPEN_CMD = "TF_CMD_94627a8ebd9fbe7f"
SOURCE_OPEN_CMD_REPEAT = "TF_CMD_2a23128b108875b9"
ORIG_TRADE_ID = "trd_57a0e534ebdb4803"
ORIG_POS_ID = "pos_192ae781c3b541c3"
TRIGGER = f"SYSTEM_BUG_EXECUTION_MARKET_NOT_READY_MISSED_OPEN|H1|{SOURCE_OPEN_CMD}"
RECOVERY = "SYSTEM_BUG_EXECUTION_MARKET_NOT_READY_MISSED_OPEN"
ENTRY_TS = "2026-09-21T08:45:00Z"
EXIT_TS = "2026-09-21T09:15:00Z"
ORIG_EXIT_TS = "2026-09-21T09:00:00Z"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _load_trade(books: EpochBooks, trade_id: str) -> dict:
    for row in books.read_all("trades"):
        if str(row.get("trade_id")) == trade_id:
            return dict(row)
    raise SystemExit(f"missing trade {trade_id}")


def already_recovered(books: EpochBooks) -> bool:
    for row in books.read_all("trades"):
        if str(row.get("trigger_event_id") or "") == TRIGGER:
            return True
        if (
            str(row.get("source_command_id") or "") == SOURCE_OPEN_CMD
            and str(row.get("recovery_reason") or "") == RECOVERY
        ):
            return True
    return False


def mark_commands(ids: list[str]) -> None:
    payload = json.loads(CURSOR_PATH.read_text(encoding="utf-8"))
    have = [str(x) for x in (payload.get("processed_command_ids") or [])]
    for cid in ids:
        if cid not in have:
            have.append(cid)
    payload["processed_command_ids"] = have
    payload["updated_at"] = _utc()
    tmp = CURSOR_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(CURSOR_PATH)


def main() -> None:
    cfg = load_intrabar_paper_config(OVERLAY)
    books = EpochBooks(BOOKS_ROOT, paper_epoch_id=EPOCH)
    performed = _utc()
    orig = _load_trade(books, ORIG_TRADE_ID)

    already_restated = any(
        str(row.get("supersedes_trade_id") or "") == ORIG_TRADE_ID
        and str(row.get("recovery_reason") or "") == "TAKE_PROFIT_BAR_CLOSE_RESTATE"
        for row in books.read_all("trades")
    )
    recovered = already_recovered(books)
    if already_restated and recovered:
        mark_commands([SOURCE_OPEN_CMD, SOURCE_OPEN_CMD_REPEAT])
        print(json.dumps({"status": "ALREADY_RECOVERED"}))
        return

    restated_id = None
    if not already_restated:
        restated_id = _id("trd")
        restated = dict(orig)
        restated.update(
            {
                "trade_id": restated_id,
                "exit_ts": ORIG_EXIT_TS,
                "execution_timestamp": ORIG_EXIT_TS,
                "context_occurrence_timestamp": ORIG_EXIT_TS,
                "supersedes_trade_id": ORIG_TRADE_ID,
                "recovery_reason": "TAKE_PROFIT_BAR_CLOSE_RESTATE",
                "recovery_performed_at": performed,
                "recovery_note": "H1 TP printed on 08:00 bar; restamp exclusive-end onto 09:00 close (paper hung 08:45-09:09).",
            }
        )
        books.append("trades", restated)
        books.append(
            "positions",
            {
                "position_id": ORIG_POS_ID,
                "timeframe": "H1",
                "side": "LONG",
                "status": "CLOSED",
                "quantity": orig.get("quantity"),
                "entry_price": orig.get("entry_price"),
                "exit_price": orig.get("exit_price"),
                "stop_loss_price": orig.get("stop_loss_price"),
                "take_profit_price": orig.get("take_profit_price"),
                "lifecycle_episode_id": orig.get("lifecycle_episode_id"),
                "opened_at": orig.get("entry_ts"),
                "closed_at": ORIG_EXIT_TS,
                "exit_reason": "TAKE_PROFIT",
                "recovery_reason": "TAKE_PROFIT_BAR_CLOSE_RESTATE",
                "recovery_performed_at": performed,
            },
        )

    if recovered:
        mark_commands([SOURCE_OPEN_CMD, SOURCE_OPEN_CMD_REPEAT])
        print(json.dumps({"status": "ALREADY_RECOVERED", "restated_trade_id": restated_id}))
        return

    sleeves = SleeveLedger.load(EPOCH_ROOT)
    if sleeves is None:
        raise SystemExit("missing sleeve ledger")
    h1 = sleeves.get("H1")
    entry = float(orig["exit_price"])
    sizing = resolve_risk_sizing(
        cfg=cfg,
        side="LONG",
        entry_price=entry,
        equity_usd=float(h1.current_equity_usd),
        risk_budget_usd=float(h1.next_risk_budget_usd),
    )
    if not sizing.ok or sizing.quantity is None or sizing.take_profit_price is None:
        raise SystemExit(f"sizing failed: {sizing.block_reason}")

    qty = float(sizing.quantity)
    take = float(sizing.take_profit_price)
    stop = float(sizing.stop_loss_price)
    risk = float(sizing.risk_amount_usd)
    econ = closed_trade_economics(
        cfg=cfg,
        side="LONG",
        entry_price=entry,
        exit_price=take,
        quantity=qty,
        risk_amount_usd=risk,
        exit_reason="TP",
    )
    pos_id = _id("pos")
    trade_id = _id("trd")
    cmd_id = _id("cmd")
    order_in = _id("ord")
    order_out = _id("ord")
    fill_in = _id("fill")
    fill_out = _id("fill")

    books.append(
        "positions",
        {
            "position_id": pos_id,
            "timeframe": "H1",
            "side": "LONG",
            "status": "OPEN",
            "quantity": qty,
            "entry_price": entry,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "lifecycle_episode_id": orig.get("lifecycle_episode_id"),
            "opened_at": ENTRY_TS,
            "entry_command_id": SOURCE_OPEN_CMD,
        },
    )
    books.append(
        "fills",
        {
            "fill_id": fill_in,
            "order_id": order_in,
            "command_id": cmd_id,
            "timeframe": "H1",
            "side": "LONG",
            "action": "ENTRY",
            "paper_fill_price": entry,
            "quantity": qty,
            "position_id": pos_id,
            "ts": ENTRY_TS,
            "recovery_reason": RECOVERY,
        },
    )
    books.append(
        "fills",
        {
            "fill_id": fill_out,
            "order_id": order_out,
            "command_id": cmd_id,
            "timeframe": "H1",
            "side": "LONG",
            "action": "EXIT",
            "paper_fill_price": take,
            "quantity": qty,
            "position_id": pos_id,
            "trigger_type": "TP",
            "trigger_event_id": TRIGGER,
            "trigger_price": take,
            "ts": EXIT_TS,
            "recovery_reason": RECOVERY,
        },
    )
    books.append(
        "commands",
        {
            "command_id": cmd_id,
            "timeframe": "H1",
            "side": "LONG",
            "action": "ENTRY",
            "paper_fill_price": entry,
            "ts": ENTRY_TS,
            "recovery_reason": RECOVERY,
            "source_command_id": SOURCE_OPEN_CMD,
        },
    )
    books.append(
        "positions",
        {
            "position_id": pos_id,
            "timeframe": "H1",
            "side": "LONG",
            "status": "CLOSED",
            "quantity": qty,
            "entry_price": entry,
            "exit_price": take,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "lifecycle_episode_id": orig.get("lifecycle_episode_id"),
            "opened_at": ENTRY_TS,
            "closed_at": EXIT_TS,
            "exit_reason": "TP",
            "recovery_reason": RECOVERY,
            "recovery_performed_at": performed,
        },
    )
    books.append(
        "trades",
        {
            "trade_id": trade_id,
            "position_id": pos_id,
            "timeframe": "H1",
            "side": "LONG",
            "quantity": qty,
            "entry_price": entry,
            "exit_price": take,
            "take_profit_price": take,
            "stop_loss_price": stop,
            "gross_pnl_usd": econ["gross_pnl_usd"],
            "net_pnl_usd": econ["net_pnl_usd"],
            "fees_usd": econ["fees_usd"],
            "slippage_usd": econ["slippage_usd"],
            "entry_fee_usd": econ["entry_fee_usd"],
            "exit_fee_usd": econ["exit_fee_usd"],
            "risk_amount_usd": risk,
            "r_multiple": econ["r_multiple"],
            "exit_reason": "TP",
            "lifecycle_episode_id": orig.get("lifecycle_episode_id"),
            "entry_ts": ENTRY_TS,
            "exit_ts": EXIT_TS,
            "status": "CLOSED",
            "statistics_included": True,
            "recovery_reason": RECOVERY,
            "recovery_performed_at": performed,
            "recovery_note": (
                "S4.1 H1 TP_SL_CONTINUATION_OPEN after spike TP was not filled: "
                "paper hung 08:45Z then RECOVERING/DEGRADED."
            ),
            "source_command_id": SOURCE_OPEN_CMD,
            "trigger_event_id": TRIGGER,
            "paper_epoch_id": EPOCH,
        },
    )
    sleeve_state = sleeves.apply_realized_net_pnl("H1", float(econ["net_pnl_usd"]), at=EXIT_TS)
    master = sleeves.master_snapshot()
    books.append(
        "equity_snapshots",
        {
            "ts": EXIT_TS,
            "equity_usd": float(master["master_current_equity_usd"]),
            "realized_pnl_usd": float(master["master_realized_net_pnl_usd"]),
            "unrealized_pnl_usd": 0.0,
            "trade_id": trade_id,
            "timeframe": "H1",
            "timeframe_equity_usd": float(sleeve_state.current_equity_usd),
            "timeframe_net_pnl_usd": float(econ["net_pnl_usd"]),
            "recovery_reason": RECOVERY,
        },
    )
    mark_commands([SOURCE_OPEN_CMD, SOURCE_OPEN_CMD_REPEAT])
    print(
        json.dumps(
            {
                "status": "RECOVERED",
                "restated_trade_id": restated_id,
                "trade_id": trade_id,
                "position_id": pos_id,
                "entry": entry,
                "exit": take,
                "qty": qty,
                "net_pnl_usd": econ["net_pnl_usd"],
                "h1_equity": sleeve_state.current_equity_usd,
                "master_equity": master["master_current_equity_usd"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
