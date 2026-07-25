"""PaperTraderEngine — shared execution engine bound to one isolated book.

All execution math is delegated to :mod:`paper_core` (which re-exports the
canonical paper economics + legacy controller helpers). This engine only:

  * resolves a point-in-time fill strictly after the command timestamp
  * enforces per-book idempotency via deterministic IDs
  * writes the timeframe's own signals / orders / fills / positions / trades

It never reads or writes another timeframe's book, and never touches
cognition, context, or decision datasets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .paper_core import (
    APPROVAL_PHRASE,
    ECONOMICS_SOURCE,
    MAX_RISK_USD,
    ORDER_COLUMNS,
    POSITION_COLUMNS,
    SIGNAL_COLUMNS,
    TRADE_COLUMNS,
    closed_trade_economics,
    compute_stop_take,
    fill_after_decision_ok,
    make_id,
    metadata_json,
    resolve_risk_sizing,
    safe_float,
)
from .trader_book import CLOSED_TRADE_COLUMNS, TraderBook, atomic_write_parquet

OPEN_INTENTS = {"OPEN_LONG", "OPEN_SHORT"}
CLOSE_INTENT = "CLOSE"
HOLD_INTENT = "HOLD"
NO_ACTION_INTENT = "NO_ACTION"

RESULT_OPENED = "OPENED"
RESULT_CLOSED = "CLOSED"
RESULT_HELD = "POSITION_HELD"
RESULT_NO_ACTION = "NO_ACTION"
RESULT_NO_FILL = "NO_FILL"
RESULT_BLOCKED = "BLOCKED"
RESULT_ALREADY_APPLIED = "ALREADY_APPLIED"
RESULT_EXPIRED = "COMMAND_EXPIRED"

# NO_FILL is retried on later cycles until the command TTL expires, so it must
# not consume the command cursor.
NON_CONSUMING_RESULTS = {RESULT_ALREADY_APPLIED, RESULT_NO_FILL}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return ts.isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _append(path, columns: list[str], record: dict[str, Any], existing: pd.DataFrame) -> None:
    row = pd.DataFrame([{c: record.get(c) for c in columns}], columns=columns)
    if len(existing):
        base = existing.copy()
        for col in columns:
            if col not in base.columns:
                base[col] = None
        base = base[columns]
        out = pd.concat([base, row], ignore_index=True)
    else:
        out = row
    atomic_write_parquet(path, out)


@dataclass
class FillObservation:
    available: bool
    price: float | None
    timestamp: str | None
    high: float | None
    low: float | None
    reason: str | None
    source: str


def resolve_point_in_time_fill(
    feed: pd.DataFrame,
    *,
    after_timestamp: Any,
    ts_column: str | None = None,
) -> FillObservation:
    """First completed market observation strictly after the command timestamp.

    Comparison uses bar *close* times, so the bar whose close produced the
    command can never fill it (no same-bar look-ahead).
    """
    if feed is None or not len(feed):
        return FillObservation(False, None, None, None, None, "NO_FILL_NO_MARKET_DATA", "live_market_feed")
    if ts_column is None:
        ts_column = "bar_close_timestamp" if "bar_close_timestamp" in feed.columns else "timestamp"
    if ts_column not in feed.columns:
        return FillObservation(False, None, None, None, None, "NO_FILL_NO_MARKET_DATA", "live_market_feed")
    boundary = pd.Timestamp(after_timestamp)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    stamps = pd.to_datetime(feed[ts_column], utc=True, errors="coerce")
    mask = stamps > boundary
    if not bool(mask.any()):
        return FillObservation(
            False, None, None, None, None, "NO_FILL_NO_COMPLETED_BAR_AFTER_COMMAND", "live_market_feed"
        )
    idx = stamps[mask].index[0]
    row = feed.loc[idx]
    price = safe_float(row.get("close"))
    if price is None or price <= 0:
        return FillObservation(False, None, None, None, None, "NO_FILL_INVALID_PRICE", "live_market_feed")
    return FillObservation(
        True,
        float(price),
        _iso(stamps.loc[idx]),
        safe_float(row.get("high")),
        safe_float(row.get("low")),
        None,
        "live_market_feed_completed_bar_close",
    )


class PaperTraderEngine:
    """One engine instance per timeframe book."""

    def __init__(self, book: TraderBook, *, symbol: str = "BTCUSDT") -> None:
        self.book = book
        self.timeframe = book.timeframe
        self.symbol = symbol

    # --- identity -----------------------------------------------------------
    def _ids_for(self, command: dict[str, Any], phase: str) -> dict[str, str]:
        key = (
            self.timeframe,
            command.get("asset") or self.symbol,
            command.get("evaluation_timestamp"),
            command.get("lifecycle_episode_id"),
            command.get("intent"),
            phase,
        )
        return {
            "signal_id": make_id(f"TF_SIGNAL_{self.timeframe}", *key),
            "order_id": make_id(f"TF_ORDER_{self.timeframe}", *key),
            "fill_id": make_id(f"TF_FILL_{self.timeframe}", *key),
            "position_id": make_id(f"TF_POSITION_{self.timeframe}", *key),
            "trade_id": make_id(f"TF_TRADE_{self.timeframe}", *key),
        }

    def already_applied(self, command_id: str) -> bool:
        state = self.book.load_controller_state()
        return command_id in (state.get("processed_command_ids") or [])

    # --- sizing -------------------------------------------------------------
    def _sizing(self, *, side: str, entry_price: float, approved_risk_usd: float) -> dict[str, Any]:
        stop, take = compute_stop_take(side, entry_price)
        canonical = resolve_risk_sizing(
            side=side,
            entry_price=entry_price,
            stop_loss_price=stop,
            take_profit_price=take,
        )
        payload = canonical.to_controller_dict()
        if not payload.get("allowed"):
            return payload
        # Canonical sizing is linear in risk; scale to the trader's approved
        # portfolio slice without introducing a second sizing formula.
        scale = float(approved_risk_usd) / float(MAX_RISK_USD) if MAX_RISK_USD else 0.0
        if scale <= 0:
            payload["allowed"] = False
            payload["reason"] = "PORTFOLIO_RISK_LIMIT"
            return payload
        for key in (
            "quantity_btc",
            "position_size_btc",
            "notional_usd",
            "position_notional_usd",
            "entry_fee_usd",
            "estimated_exit_fee_usd_at_stop",
            "entry_slippage_usd",
            "estimated_exit_slippage_usd_at_stop",
            "estimated_slippage_usd_at_stop",
            "estimated_loss_at_stop",
            "estimated_loss_at_stop_usd",
        ):
            value = safe_float(payload.get(key))
            if value is not None:
                payload[key] = value * scale
        payload["risk_amount_usd"] = float(approved_risk_usd)
        payload["max_risk_usd"] = float(approved_risk_usd)
        payload["risk_scale_from_canonical"] = scale
        payload["timeframe"] = self.timeframe
        return payload

    # --- main entry point ----------------------------------------------------
    def apply_command(
        self,
        command: dict[str, Any],
        *,
        feed: pd.DataFrame,
    ) -> dict[str, Any]:
        command_id = str(command.get("command_id") or "")
        intent = str(command.get("intent") or NO_ACTION_INTENT).upper()
        tf = str(command.get("timeframe") or "").upper()
        if tf != self.timeframe:
            return self._result(
                command,
                RESULT_BLOCKED,
                reason="COMMAND_TIMEFRAME_MISMATCH",
                detail=f"engine={self.timeframe} command={tf}",
            )
        if self.already_applied(command_id):
            return self._result(command, RESULT_ALREADY_APPLIED, reason="IDEMPOTENT_REPLAY")

        open_position = self.book.open_position()

        if intent in OPEN_INTENTS:
            outcome = self._open(command, feed=feed, open_position=open_position)
        elif intent == CLOSE_INTENT:
            outcome = self._close(command, feed=feed, open_position=open_position)
        elif intent == HOLD_INTENT:
            outcome = self._result(
                command,
                RESULT_HELD if open_position else RESULT_NO_ACTION,
                reason="HOLD_UNTIL_DIRECTIONAL_CONTEXT_END" if open_position else "NO_OPEN_POSITION",
                position_id=(open_position or {}).get("position_id"),
            )
        else:
            outcome = self._result(
                command,
                RESULT_NO_ACTION,
                reason=(command.get("reason_codes") or ["NO_ACTION"])[0]
                if isinstance(command.get("reason_codes"), list)
                else str(command.get("reason_codes") or "NO_ACTION"),
            )

        self._record_cursor(command, outcome)
        return outcome

    # --- open ---------------------------------------------------------------
    def _open(
        self,
        command: dict[str, Any],
        *,
        feed: pd.DataFrame,
        open_position: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if open_position:
            return self._result(
                command,
                RESULT_BLOCKED,
                reason="POSITION_ALREADY_OPEN",
                position_id=open_position.get("position_id"),
            )
        if not bool(command.get("action_allowed")):
            return self._result(
                command,
                RESULT_BLOCKED,
                reason=str((command.get("reason_codes") or ["ACTION_NOT_ALLOWED"])[0]),
            )
        approved = safe_float(command.get("approved_risk_usd")) or 0.0
        if approved <= 0:
            return self._result(command, RESULT_BLOCKED, reason="PORTFOLIO_RISK_LIMIT")

        evaluation_ts = command.get("evaluation_timestamp")
        fill = resolve_point_in_time_fill(feed, after_timestamp=evaluation_ts)
        if not fill.available:
            return self._result(command, RESULT_NO_FILL, reason=fill.reason)
        guard = fill_after_decision_ok(
            decision={"candle_timestamp": evaluation_ts},
            execution_ts=fill.timestamp,
        )
        if not guard.get("ok"):
            return self._result(command, RESULT_NO_FILL, reason=str(guard.get("reason")))

        side = "LONG" if command["intent"] == "OPEN_LONG" else "SHORT"
        sizing = self._sizing(side=side, entry_price=fill.price, approved_risk_usd=approved)
        if not sizing.get("allowed"):
            reason = str(sizing.get("reason") or "INVALID_STOP_DISTANCE")
            if "INVALID_STOP" in reason:
                reason = "INVALID_STOP_DISTANCE"
            return self._result(command, RESULT_BLOCKED, reason=reason)

        ids = self._ids_for(command, "OPEN")
        qty = float(sizing["quantity_btc"])
        notional = float(sizing["notional_usd"])
        stop = float(sizing["stop_loss_price"])
        take = float(sizing["take_profit_price"])
        entry_fee = float(sizing["entry_fee_usd"])
        entry_slip = float(sizing["entry_slippage_usd"])
        order_side = "BUY" if side == "LONG" else "SELL"
        now = _utc_now()

        lineage = {
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
            "manager_cycle_id": command.get("manager_cycle_id"),
            "lifecycle_episode_id": command.get("lifecycle_episode_id"),
            "lifecycle_phase": command.get("lifecycle_phase"),
            "timeframe_state": command.get("timeframe_state"),
            "timeframe_direction": command.get("timeframe_direction"),
            "source_bar_open": command.get("source_bar_open"),
            "source_bar_close": command.get("source_bar_close"),
            "source_state_timestamp": command.get("source_state_timestamp"),
            "evaluation_timestamp": command.get("evaluation_timestamp"),
            "fill_timestamp": fill.timestamp,
            "fill_source": fill.source,
            "approved_risk_usd": approved,
            "requested_risk_usd": command.get("requested_risk_usd"),
            "portfolio_open_risk_usd": command.get("portfolio_open_risk_usd"),
            "economics_source": ECONOMICS_SOURCE,
            "sizing": {k: sizing.get(k) for k in ("sizing_method", "risk_scale_from_canonical", "stop_distance")},
            "stop_loss_price": stop,
            "take_profit_price": take,
            "entry_price": fill.price,
            "entry_price_source": fill.source,
            "quantity_btc": qty,
            "notional_usd": notional,
            "entry_fee_usd": entry_fee,
            "side": side,
            "parent_signal_id": ids["signal_id"],
            "parent_order_id": ids["order_id"],
            "parent_trade_id": ids["fill_id"],
            "paper_position_id": ids["position_id"],
            "position_status": "OPEN",
            "paper_only": True,
            "execution_enabled": False,
            "no_exchange_api_call": True,
        }

        signal = {
            "signal_id": ids["signal_id"],
            "signal_status": "ACCEPTED",
            "signal_source": f"TIMEFRAME_MANAGER_{self.timeframe}",
            "decision_log_ts": command.get("evaluation_timestamp"),
            "source_context_ts": command.get("source_state_timestamp"),
            "context": command.get("timeframe_state"),
            "lifecycle_state": command.get("lifecycle_phase"),
            "stale_flag": False,
            "side": side,
            "policy_action": command.get("intent"),
            "paper_action": f"INTENT_OPEN_{side}",
            "paper_intent": command.get("intent"),
            "order_side": order_side,
            "position_effect": "OPEN",
            "entry_price_source": fill.source,
            "entry_price": fill.price,
            "context_episode_id": command.get("lifecycle_episode_id"),
            "execution_observation_price": fill.price,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "confidence": command.get("confidence"),
            "expected_edge_bps": command.get("expected_edge_bps"),
            "is_live_trade": False,
            "is_paper_trade": True,
            "is_candidate_preview": False,
            "is_research_visualization": False,
            "paper_order_write_allowed": True,
            "paper_trade_write_allowed": True,
            "paper_position_write_allowed": True,
            "paper_ledger_write_allowed": True,
            "execution_enabled": False,
            "created_at_utc": now,
            "approval_phrase": APPROVAL_PHRASE,
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        order = {
            "paper_order_id": ids["order_id"],
            "created_at": now,
            "decision_id": command.get("command_id"),
            "candle_timestamp": fill.timestamp,
            "symbol": self.symbol,
            "side": order_side,
            "order_type": "MARKET",
            "quantity": qty,
            "requested_price": fill.price,
            "notional": notional,
            "status": "FILLED",
            "fill_price": fill.price,
            "filled_quantity": qty,
            "fee_bps": float(sizing["entry_fee_bps"]),
            "slippage_bps": float(sizing["entry_slippage_bps"]),
            "paper_only": True,
            "execution_enabled": False,
            "risk_gate_status": "APPROVED",
            "risk_block_reason": None,
            "metadata_json": metadata_json(lineage),
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        fill_row = {
            "paper_trade_id": ids["fill_id"],
            "paper_order_id": ids["order_id"],
            "position_id": ids["position_id"],
            "timestamp": fill.timestamp,
            "symbol": self.symbol,
            "side": order_side,
            "quantity": qty,
            "price": fill.price,
            "notional": notional,
            "fee": entry_fee,
            "fee_bps": float(sizing["entry_fee_bps"]),
            "slippage": entry_slip,
            "slippage_bps": float(sizing["entry_slippage_bps"]),
            "realized_pnl": 0.0,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": metadata_json(lineage),
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        position = {
            "position_id": ids["position_id"],
            "opened_at": fill.timestamp,
            "closed_at": None,
            "symbol": self.symbol,
            "direction": side,
            "quantity": qty,
            "entry_price": fill.price,
            "exit_price": None,
            "notional": notional,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": entry_fee,
            "slippage_paid": entry_slip,
            "status": "OPEN",
            "opening_decision_id": command.get("command_id"),
            "closing_decision_id": None,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": metadata_json(lineage),
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }

        self.book.ensure_dirs()
        _append(self.book.signals, SIGNAL_COLUMNS + ["timeframe", "command_id"], signal, self.book.signals_frame())
        _append(self.book.orders, ORDER_COLUMNS + ["timeframe", "command_id"], order, self.book.orders_frame())
        _append(self.book.fills, TRADE_COLUMNS + ["timeframe", "command_id"], fill_row, self.book.fills_frame())
        _append(
            self.book.positions,
            POSITION_COLUMNS + ["timeframe", "command_id"],
            position,
            self.book.positions_frame(),
        )
        return self._result(
            command,
            RESULT_OPENED,
            reason="OPENED_FROM_TIMEFRAME_COMMAND",
            position_id=ids["position_id"],
            extra={
                "side": side,
                "entry_price": fill.price,
                "fill_timestamp": fill.timestamp,
                "quantity": qty,
                "notional_usd": notional,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "approved_risk_usd": approved,
                "estimated_loss_at_stop_usd": sizing.get("estimated_loss_at_stop_usd"),
                "signal_id": ids["signal_id"],
                "order_id": ids["order_id"],
                "fill_id": ids["fill_id"],
            },
        )

    # --- close --------------------------------------------------------------
    def _close(
        self,
        command: dict[str, Any],
        *,
        feed: pd.DataFrame,
        open_position: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not open_position:
            return self._result(command, RESULT_NO_ACTION, reason="NO_OPEN_POSITION")
        position_id = str(open_position.get("position_id"))
        meta = open_position.get("metadata_json")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}

        evaluation_ts = command.get("evaluation_timestamp")
        exit_reason = str(command.get("exit_reason") or "CONTEXT_EXIT")
        fill = resolve_point_in_time_fill(feed, after_timestamp=evaluation_ts)
        if not fill.available:
            return self._result(command, RESULT_NO_FILL, reason=fill.reason, position_id=position_id)
        guard = fill_after_decision_ok(
            decision={"candle_timestamp": evaluation_ts},
            execution_ts=fill.timestamp,
        )
        if not guard.get("ok"):
            return self._result(command, RESULT_NO_FILL, reason=str(guard.get("reason")), position_id=position_id)

        side = str(open_position.get("direction") or "").upper()
        qty = float(safe_float(open_position.get("quantity")) or 0.0)
        entry_price = float(safe_float(open_position.get("entry_price")) or 0.0)
        stop = safe_float(meta.get("stop_loss_price"))
        take = safe_float(meta.get("take_profit_price"))
        approved_risk = safe_float(meta.get("approved_risk_usd")) or MAX_RISK_USD

        exit_price = float(fill.price)
        if "STOP" in exit_reason.upper() and stop is not None:
            exit_price = float(stop)
        elif "TAKE" in exit_reason.upper() and take is not None:
            exit_price = float(take)

        econ = closed_trade_economics(
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size_btc=qty,
            stop_loss_price=stop,
            take_profit_price=take,
            risk_amount_usd=approved_risk,
            exit_reason=exit_reason,
            exit_execution_source=fill.source,
        )

        ids = self._ids_for(command, "CLOSE")
        order_side = "SELL" if side == "LONG" else "BUY"
        now = _utc_now()
        lineage = {
            **meta,
            "timeframe": self.timeframe,
            "closing_command_id": command.get("command_id"),
            "closed_at": fill.timestamp,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "exit_execution_source": fill.source,
            "position_status": "CLOSED",
            "economics": {k: econ.get(k) for k in ("fees_usd", "slippage_usd", "gross_pnl_usd", "net_pnl_usd", "R")},
            "paper_only": True,
            "execution_enabled": False,
        }

        signal = {
            "signal_id": ids["signal_id"],
            "signal_status": "ACCEPTED",
            "signal_source": f"TIMEFRAME_MANAGER_{self.timeframe}",
            "decision_log_ts": evaluation_ts,
            "source_context_ts": command.get("source_state_timestamp"),
            "context": command.get("timeframe_state"),
            "lifecycle_state": command.get("lifecycle_phase"),
            "stale_flag": False,
            "side": side,
            "policy_action": f"CLOSE_{side}_{exit_reason}",
            "paper_action": f"INTENT_CLOSE_{side}",
            "paper_intent": "CLOSE",
            "order_side": order_side,
            "position_effect": "CLOSE",
            "entry_price_source": fill.source,
            "entry_price": exit_price,
            "context_episode_id": command.get("lifecycle_episode_id"),
            "stop_loss_price": stop,
            "take_profit_price": take,
            "is_live_trade": False,
            "is_paper_trade": True,
            "is_candidate_preview": False,
            "is_research_visualization": False,
            "paper_order_write_allowed": True,
            "paper_trade_write_allowed": True,
            "paper_position_write_allowed": True,
            "paper_ledger_write_allowed": True,
            "execution_enabled": False,
            "created_at_utc": now,
            "approval_phrase": APPROVAL_PHRASE,
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        order = {
            "paper_order_id": ids["order_id"],
            "created_at": now,
            "decision_id": command.get("command_id"),
            "candle_timestamp": fill.timestamp,
            "symbol": self.symbol,
            "side": order_side,
            "order_type": "MARKET",
            "quantity": qty,
            "requested_price": exit_price,
            "notional": float(econ["exit_notional_usd"]),
            "status": "FILLED",
            "fill_price": exit_price,
            "filled_quantity": qty,
            "fee_bps": float(econ["exit_fee_bps"]),
            "slippage_bps": float(econ["exit_slippage_bps"]),
            "paper_only": True,
            "execution_enabled": False,
            "risk_gate_status": "APPROVED",
            "risk_block_reason": None,
            "metadata_json": metadata_json(lineage),
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        fill_row = {
            "paper_trade_id": ids["fill_id"],
            "paper_order_id": ids["order_id"],
            "position_id": position_id,
            "timestamp": fill.timestamp,
            "symbol": self.symbol,
            "side": order_side,
            "quantity": qty,
            "price": exit_price,
            "notional": float(econ["exit_notional_usd"]),
            "fee": float(econ["exit_fee_usd"]),
            "fee_bps": float(econ["exit_fee_bps"]),
            "slippage": float(econ["exit_slippage_usd"]),
            "slippage_bps": float(econ["exit_slippage_bps"]),
            "realized_pnl": float(econ["net_pnl_usd"]),
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": metadata_json(lineage),
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
        }
        closed_trade = {
            "trade_id": ids["trade_id"],
            "timeframe": self.timeframe,
            "position_id": position_id,
            "command_id": command.get("command_id"),
            "lifecycle_episode_id": meta.get("lifecycle_episode_id"),
            "side": side,
            "quantity": qty,
            "entry_ts": open_position.get("opened_at"),
            "exit_ts": fill.timestamp,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "notional_usd": float(econ["entry_notional_usd"]),
            "risk_amount_usd": float(approved_risk),
            "fees_usd": float(econ["fees_usd"]),
            "slippage_usd": float(econ["slippage_usd"]),
            "gross_pnl_usd": float(econ["gross_pnl_usd"]),
            "net_pnl_usd": float(econ["net_pnl_usd"]),
            "r_multiple": float(econ["r_multiple"]),
            "exit_reason": exit_reason,
            "entry_fill_id": meta.get("parent_trade_id"),
            "exit_fill_id": ids["fill_id"],
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": metadata_json(lineage),
        }

        positions = self.book.positions_frame()
        mask = positions["position_id"].astype(str) == position_id
        positions.loc[mask, "closed_at"] = fill.timestamp
        positions.loc[mask, "exit_price"] = exit_price
        positions.loc[mask, "realized_pnl"] = float(econ["net_pnl_usd"])
        positions.loc[mask, "unrealized_pnl"] = 0.0
        positions.loc[mask, "fees_paid"] = float(econ["fees_usd"])
        positions.loc[mask, "slippage_paid"] = float(econ["slippage_usd"])
        positions.loc[mask, "status"] = "CLOSED"
        positions.loc[mask, "closing_decision_id"] = command.get("command_id")
        positions.loc[mask, "metadata_json"] = metadata_json(lineage)

        self.book.ensure_dirs()
        _append(self.book.signals, SIGNAL_COLUMNS + ["timeframe", "command_id"], signal, self.book.signals_frame())
        _append(self.book.orders, ORDER_COLUMNS + ["timeframe", "command_id"], order, self.book.orders_frame())
        _append(self.book.fills, TRADE_COLUMNS + ["timeframe", "command_id"], fill_row, self.book.fills_frame())
        atomic_write_parquet(self.book.positions, positions)
        _append(self.book.trades, CLOSED_TRADE_COLUMNS, closed_trade, self.book.trades_frame())

        return self._result(
            command,
            RESULT_CLOSED,
            reason=exit_reason,
            position_id=position_id,
            extra={
                "side": side,
                "exit_price": exit_price,
                "fill_timestamp": fill.timestamp,
                "net_pnl_usd": float(econ["net_pnl_usd"]),
                "gross_pnl_usd": float(econ["gross_pnl_usd"]),
                "fees_usd": float(econ["fees_usd"]),
                "slippage_usd": float(econ["slippage_usd"]),
                "trade_id": ids["trade_id"],
            },
        )

    # --- bookkeeping ---------------------------------------------------------
    def _result(
        self,
        command: dict[str, Any],
        result: str,
        *,
        reason: str | None = None,
        position_id: str | None = None,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "timeframe": self.timeframe,
            "command_id": command.get("command_id"),
            "manager_cycle_id": command.get("manager_cycle_id"),
            "intent": command.get("intent"),
            "evaluation_timestamp": command.get("evaluation_timestamp"),
            "result": result,
            "reason": reason,
            "detail": detail,
            "position_id": position_id,
            "paper_only": True,
            "execution_enabled": False,
            "exchange_calls": 0,
            "applied_at": _utc_now(),
        }
        if extra:
            payload.update(extra)
        return payload

    def expire_command(self, command: dict[str, Any]) -> dict[str, Any]:
        outcome = self._result(command, RESULT_EXPIRED, reason="COMMAND_TTL_EXPIRED_NO_FILL")
        self._record_cursor(command, outcome)
        return outcome

    def _record_cursor(self, command: dict[str, Any], outcome: dict[str, Any]) -> None:
        if outcome.get("result") == RESULT_ALREADY_APPLIED:
            return
        state = self.book.load_controller_state()
        processed = list(state.get("processed_command_ids") or [])
        command_id = str(command.get("command_id") or "")
        if command_id and command_id not in processed and outcome.get("result") not in NON_CONSUMING_RESULTS:
            processed.append(command_id)
        open_position = self.book.open_position()
        state.update(
            {
                "timeframe": self.timeframe,
                "processed_command_ids": processed[-500:],
                "last_command_id": command_id,
                "last_command_evaluation_timestamp": command.get("evaluation_timestamp"),
                "cursor_evaluation_timestamp": command.get("evaluation_timestamp"),
                "last_result": outcome.get("result"),
                "last_reason": outcome.get("reason"),
                "open_position_id": (open_position or {}).get("position_id"),
                "cycles": int(state.get("cycles") or 0) + 1,
                "updated_at": _utc_now(),
                "paper_only": True,
                "execution_enabled": False,
                "shared_core": "shared_paper_execution_core_v1",
            }
        )
        self.book.save_controller_state(state)

    # --- read-model ----------------------------------------------------------
    def snapshot(self, *, mark_price: float | None = None) -> dict[str, Any]:
        open_position = self.book.open_position()
        trades = self.book.trades_frame()
        realized = float(pd.to_numeric(trades["net_pnl_usd"], errors="coerce").fillna(0).sum()) if len(trades) else 0.0
        fees = float(pd.to_numeric(trades["fees_usd"], errors="coerce").fillna(0).sum()) if len(trades) else 0.0
        slippage = (
            float(pd.to_numeric(trades["slippage_usd"], errors="coerce").fillna(0).sum()) if len(trades) else 0.0
        )
        unrealized = 0.0
        open_risk = 0.0
        if open_position:
            meta = open_position.get("metadata_json")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            meta = meta if isinstance(meta, dict) else {}
            open_risk = float(safe_float(meta.get("approved_risk_usd")) or 0.0)
            qty = float(safe_float(open_position.get("quantity")) or 0.0)
            entry = float(safe_float(open_position.get("entry_price")) or 0.0)
            if mark_price is not None and qty and entry:
                direction = str(open_position.get("direction") or "").upper()
                unrealized = (
                    (float(mark_price) - entry) * qty if direction == "LONG" else (entry - float(mark_price)) * qty
                )
        state = self.book.load_controller_state()
        return {
            "timeframe": self.timeframe,
            "open_position": None
            if not open_position
            else {
                "position_id": open_position.get("position_id"),
                "direction": open_position.get("direction"),
                "quantity": safe_float(open_position.get("quantity")),
                "entry_price": safe_float(open_position.get("entry_price")),
                "opened_at": open_position.get("opened_at"),
                "status": open_position.get("status"),
            },
            "open_risk_usd": open_risk,
            "realized_pnl_usd": realized,
            "unrealized_pnl_usd": unrealized,
            "fees_paid_usd": fees,
            "slippage_paid_usd": slippage,
            "closed_trades": int(len(trades)),
            "last_command_id": state.get("last_command_id"),
            "last_result": state.get("last_result"),
            "last_reason": state.get("last_reason"),
            "cursor_evaluation_timestamp": state.get("cursor_evaluation_timestamp"),
        }
