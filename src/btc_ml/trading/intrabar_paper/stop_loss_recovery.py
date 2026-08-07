"""Append-only recovery for missed protective stop-loss closes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .books import EpochBooks
from .config import IntrabarPaperConfig
from .economics import closed_trade_economics
from .position_invalidation import latest_position_row
from .sleeves import SleeveLedger

RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS = "SYSTEM_BUG_STOP_LOSS_RECOVERY"
METRIC_TYPE_STOP_LOSS_RECOVERY = "STOP_LOSS_RECOVERY"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def recovery_trigger_event_id(position_id: str) -> str:
    return f"SYSTEM_BUG_STOP_LOSS_RECOVERY|{position_id}"


def find_recovery_trade(books: EpochBooks, position_id: str) -> dict[str, Any] | None:
    for row in books.read_all("trades"):
        if str(row.get("position_id") or "") != position_id:
            continue
        if str(row.get("recovery_reason") or "") == RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS:
            return dict(row)
        if (
            str(row.get("exit_reason") or "").upper() == "SL"
            and str(row.get("trigger_event_id") or "").startswith("SYSTEM_BUG_STOP_LOSS_RECOVERY|")
        ):
            return dict(row)
    return None


def recover_missed_stop_loss(
    books: EpochBooks,
    *,
    position_id: str,
    exit_price: float,
    cfg: IntrabarPaperConfig,
    epoch_root: Path,
    recovery_reason: str = RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS,
    recovery_performed_at: str | None = None,
    recovery_note: str | None = None,
) -> dict[str, Any]:
    """Close an OPEN position at a fixed stop price via append-only ledger recovery."""
    existing = find_recovery_trade(books, position_id)
    if existing is not None:
        latest = latest_position_row(books, position_id)
        return {
            "status": "ALREADY_RECOVERED",
            "trade": existing,
            "position": latest,
            "idempotent": True,
        }

    current = latest_position_row(books, position_id)
    if current is None:
        raise ValueError(f"position not found: {position_id}")

    status = str(current.get("status") or "").upper()
    if status == "CLOSED":
        raise ValueError(f"position {position_id} already CLOSED without recovery trade")
    if status != "OPEN":
        raise ValueError(f"position {position_id} is not OPEN (status={status!r})")

    fill_px = float(exit_price)
    side = str(current.get("side") or "").upper()
    quantity = float(current.get("quantity") or 0.0)
    entry_price = float(current.get("entry_price") or 0.0)
    risk_amount_usd = float(current.get("risk_amount_usd") or 0.0)
    timeframe = str(current.get("timeframe") or "").upper()

    econ = closed_trade_economics(
        cfg=cfg,
        side=side,
        entry_price=entry_price,
        exit_price=fill_px,
        quantity=quantity,
        risk_amount_usd=risk_amount_usd,
        exit_reason="SL",
    )

    performed_at = recovery_performed_at or _utc_iso()
    trigger_event_id = recovery_trigger_event_id(position_id)
    context_event_id = str(current.get("entry_context_event_id") or trigger_event_id)
    trigger_monotonic_ns = int(current.get("entry_monotonic_ns") or 0)

    cmd_id = _new_id("cmd")
    order_id = _new_id("ord")
    fill_id = _new_id("fill")
    trade_id = _new_id("trd")

    command = books.append(
        "commands",
        {
            "command_id": cmd_id,
            "timeframe": timeframe,
            "side": side,
            "action": "EXIT",
            "trigger_type": "SL",
            "trigger_event_id": trigger_event_id,
            "trigger_timestamp": None,
            "trigger_monotonic_ns": trigger_monotonic_ns,
            "trigger_price": fill_px,
            "context_event_id": context_event_id,
            "command_monotonic_ns": trigger_monotonic_ns,
            "book_update_id": None,
            "best_bid": None,
            "best_ask": None,
            "bbo_receive_timestamp": None,
            "bbo_receive_monotonic_ns": None,
            "bbo_age_ms": None,
            "fill_bid": None,
            "fill_ask": None,
            "paper_fill_price": fill_px,
            "recovery_reason": recovery_reason,
            "recovery_performed_at": performed_at,
            "stop_trigger_time_known": False,
            "assumed_stop_execution_price": fill_px,
            "ts": performed_at,
        },
    )
    books.append(
        "orders",
        {
            "order_id": order_id,
            "command_id": cmd_id,
            "timeframe": timeframe,
            "side": side,
            "action": "EXIT",
            "quantity": quantity,
            "status": "FILLED",
            "recovery_reason": recovery_reason,
            "ts": performed_at,
        },
    )
    fill = books.append(
        "fills",
        {
            "fill_id": fill_id,
            "order_id": order_id,
            "command_id": cmd_id,
            "timeframe": timeframe,
            "side": side,
            "action": "EXIT",
            "gross_exit_price": fill_px,
            "paper_fill_price": fill_px,
            "quantity": quantity,
            "fill_bid": None,
            "fill_ask": None,
            "trigger_type": "SL",
            "trigger_event_id": trigger_event_id,
            "trigger_timestamp": None,
            "trigger_monotonic_ns": trigger_monotonic_ns,
            "trigger_price": fill_px,
            "recovery_reason": recovery_reason,
            "recovery_performed_at": performed_at,
            "stop_trigger_time_known": False,
            "ts": performed_at,
        },
    )
    trade = books.append(
        "trades",
        {
            "trade_id": trade_id,
            "position_id": position_id,
            "timeframe": timeframe,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": fill_px,
            "gross_pnl_usd": econ["gross_pnl_usd"],
            "net_pnl_usd": econ["net_pnl_usd"],
            "fees_usd": econ["fees_usd"],
            "slippage_usd": econ["slippage_usd"],
            "entry_fee_usd": econ["entry_fee_usd"],
            "exit_fee_usd": econ["exit_fee_usd"],
            "risk_amount_usd": risk_amount_usd,
            "exit_reason": "SL",
            "lifecycle_episode_id": current.get("lifecycle_episode_id"),
            "entry_ts": current.get("opened_at"),
            "exit_ts": performed_at,
            "status": "CLOSED",
            "recovery_reason": recovery_reason,
            "recovery_performed_at": performed_at,
            "stop_trigger_time_known": False,
            "assumed_stop_execution_price": fill_px,
            "trigger_event_id": trigger_event_id,
            "recovery_note": recovery_note
            or "Missed protective stop-loss close recovered administratively.",
            "r_multiple": econ["r_multiple"],
        },
    )
    closed_position = books.append(
        "positions",
        {
            "position_id": position_id,
            "timeframe": timeframe,
            "side": side,
            "status": "CLOSED",
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": fill_px,
            "stop_loss_price": current.get("stop_loss_price"),
            "take_profit_price": current.get("take_profit_price"),
            "entry_context_event_id": current.get("entry_context_event_id"),
            "entry_fill_id": current.get("entry_fill_id"),
            "entry_command_id": current.get("entry_command_id"),
            "lifecycle_episode_id": current.get("lifecycle_episode_id"),
            "opened_at": current.get("opened_at"),
            "closed_at": performed_at,
            "exit_reason": "SL",
            "recovery_reason": recovery_reason,
            "recovery_performed_at": performed_at,
            "stop_trigger_time_known": False,
            "assumed_stop_execution_price": fill_px,
        },
    )

    sleeve_state = None
    master_snapshot = None
    sleeves = SleeveLedger.load(epoch_root)
    if sleeves is not None:
        sleeve_state = sleeves.apply_realized_net_pnl(timeframe, float(econ["net_pnl_usd"]), at=performed_at)
        master_snapshot = sleeves.master_snapshot()
        realized_pnl = float(master_snapshot["master_realized_net_pnl_usd"])
        equity = float(master_snapshot["master_current_equity_usd"])
        timeframe_equity = float(sleeve_state.current_equity_usd)
    else:
        trades = books.closed_trades()
        realized_pnl = sum(float(t.get("net_pnl_usd") or 0.0) for t in trades)
        equity = float(cfg.initial_equity_usd) + realized_pnl
        timeframe_equity = equity

    books.append(
        "equity_snapshots",
        {
            "ts": performed_at,
            "equity_usd": equity,
            "realized_pnl_usd": realized_pnl,
            "unrealized_pnl_usd": 0.0,
            "trade_id": trade_id,
            "timeframe": timeframe,
            "timeframe_equity_usd": timeframe_equity,
            "timeframe_net_pnl_usd": float(econ["net_pnl_usd"]),
            "recovery_reason": recovery_reason,
        },
    )
    audit_row = books.append(
        "metrics",
        {
            "metric_type": METRIC_TYPE_STOP_LOSS_RECOVERY,
            "position_id": position_id,
            "timeframe": timeframe,
            "side": side,
            "status": "CLOSED",
            "recovery_reason": recovery_reason,
            "recovery_performed_at": performed_at,
            "stop_trigger_time_known": False,
            "assumed_stop_execution_price": fill_px,
            "entry_price": entry_price,
            "exit_price": fill_px,
            "entry_context_event_id": current.get("entry_context_event_id"),
            "lifecycle_episode_id": current.get("lifecycle_episode_id"),
            "trade_id": trade_id,
            "net_pnl_usd": econ["net_pnl_usd"],
            "recovery_note": recovery_note
            or "Missed protective stop-loss close recovered administratively.",
        },
    )

    return {
        "status": "RECOVERED",
        "idempotent": False,
        "position_id": position_id,
        "command": command,
        "fill": fill,
        "trade": trade,
        "position": closed_position,
        "economics": econ,
        "audit": audit_row,
        "sleeve": sleeve_state.to_dict() if sleeve_state is not None else None,
        "master": master_snapshot,
    }
