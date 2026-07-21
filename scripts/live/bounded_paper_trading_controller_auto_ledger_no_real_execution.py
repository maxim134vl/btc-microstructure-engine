#!/usr/bin/env python3
"""Bounded paper trading controller (auto ledger / no real execution).

PAPER ONLY. Every interval: safety preflight → optional live context refresh +
decision-log append → monitor open paper position or evaluate flat entry →
write paper ledgers on OPEN/CLOSE → append controller cycle dataset.

Requires:
  --approved-bounded-paper-controller-auto-ledger
  --paper-only
  --no-real-execution

Approval phrase:
  APPROVE_BOUNDED_PAPER_TRADING_CONTROLLER_AUTO_LEDGER_NO_REAL_EXECUTION
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

APPROVAL_PHRASE = (
    "APPROVE_BOUNDED_PAPER_TRADING_CONTROLLER_AUTO_LEDGER_NO_REAL_EXECUTION"
)
CONTROLLER_MODE = "PAPER_ONLY"

DEFAULT_MAX_CYCLES = 96
DEFAULT_INTERVAL_SECONDS = 900
DEFAULT_MAX_DURATION_HOURS = 24

STOP_LOSS_BPS = 100.0
TAKE_PROFIT_BPS = 150.0
ENTRY_FEE_BPS = 10.0
COST_MODEL_BPS = 20.0
PAPER_INITIAL_EQUITY = 100000.0
PAPER_NOTIONAL = 10000.0
SYNTHETIC_FORBIDDEN_PRICE = 100000.0

CONTEXT_EXIT_LIFECYCLES = {
    "INVALIDATED",
    "NO_ACTIVE_CONTEXT",
    "EXPIRED",
    "TERMINATED",
}

FORBIDDEN_IMPORT_ROOTS = {"ccxt", "binance", "bybit", "exchange_api", "broker"}

RESEARCH = ROOT / "data" / "research" / "paper_simulator"
LIVE = ROOT / "data" / "live"
COGNITION = ROOT / "data" / "cognition"
LOG_PATH = ROOT / "logs" / "bounded_paper_trading_controller_auto_ledger.log"
PID_PATH = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
LOCK_PATH = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.lock"

SIGNAL_COLUMNS = [
    "signal_id",
    "signal_status",
    "signal_source",
    "decision_log_ts",
    "source_context_ts",
    "context",
    "lifecycle_state",
    "stale_flag",
    "side",
    "policy_action",
    "paper_action",
    "paper_intent",
    "order_side",
    "position_effect",
    "entry_price_source",
    "entry_price",
    "stop_loss_price",
    "take_profit_price",
    "stop_loss_bps",
    "take_profit_bps",
    "expected_edge_bps",
    "confidence",
    "cost_model_bps",
    "lookup_applied",
    "is_live_trade",
    "is_paper_trade",
    "is_candidate_preview",
    "is_research_visualization",
    "paper_order_write_allowed",
    "paper_trade_write_allowed",
    "paper_position_write_allowed",
    "paper_ledger_write_allowed",
    "execution_enabled",
    "created_at_utc",
    "approval_phrase",
]

ORDER_COLUMNS = [
    "paper_order_id",
    "created_at",
    "decision_id",
    "candle_timestamp",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "requested_price",
    "notional",
    "status",
    "fill_price",
    "filled_quantity",
    "fee_bps",
    "slippage_bps",
    "paper_only",
    "execution_enabled",
    "risk_gate_status",
    "risk_block_reason",
    "metadata_json",
]

TRADE_COLUMNS = [
    "paper_trade_id",
    "paper_order_id",
    "position_id",
    "timestamp",
    "symbol",
    "side",
    "quantity",
    "price",
    "notional",
    "fee",
    "fee_bps",
    "slippage",
    "slippage_bps",
    "realized_pnl",
    "paper_only",
    "execution_enabled",
    "metadata_json",
]

POSITION_COLUMNS = [
    "position_id",
    "opened_at",
    "closed_at",
    "symbol",
    "direction",
    "quantity",
    "entry_price",
    "exit_price",
    "notional",
    "realized_pnl",
    "unrealized_pnl",
    "fees_paid",
    "slippage_paid",
    "status",
    "opening_decision_id",
    "closing_decision_id",
    "paper_only",
    "execution_enabled",
    "metadata_json",
]

EQUITY_COLUMNS = [
    "timestamp",
    "cash",
    "position_value",
    "equity",
    "realized_pnl",
    "unrealized_pnl",
    "fees_paid",
    "slippage_paid",
    "drawdown_pct",
    "daily_pnl",
    "paper_only",
    "execution_enabled",
    "metadata_json",
]

EVENT_COLUMNS = [
    "event_id",
    "event_type",
    "timestamp",
    "decision_id",
    "candle_timestamp",
    "active_market_context",
    "raw_market_context",
    "lifecycle_state",
    "candidate_model_version",
    "candidate_prediction_label",
    "signal_direction",
    "paper_action",
    "action_reason",
    "paper_order_id",
    "position_id",
    "symbol",
    "price",
    "quantity",
    "notional",
    "fee_bps",
    "slippage_bps",
    "risk_gate_status",
    "risk_block_reason",
    "execution_enabled",
    "paper_only",
    "metadata_json",
]

CYCLE_COLUMNS = [
    "cycle_id",
    "cycle_ts",
    "market_ts",
    "decision_log_ts",
    "context",
    "lifecycle_state",
    "position_state_before",
    "action_taken",
    "signal_id",
    "order_id",
    "trade_id",
    "position_id",
    "equity_id",
    "entry_price",
    "exit_price",
    "pnl_bps",
    "pnl_usd",
    "reason",
    "exit_preview_action",
    "paper_ledger_write_performed",
    "execution_enabled",
    "exchange_api_call_used",
    "cycle_status",
]

ACTION_COLUMNS = [
    "action_id",
    "cycle_id",
    "action_ts",
    "action_type",
    "signal_id",
    "order_id",
    "trade_id",
    "position_id",
    "equity_id",
    "side",
    "price",
    "reason",
    "execution_enabled",
]

SleepFn = Callable[[float], None]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _log(msg: str, log_path: Path | None = None) -> None:
    line = f"{_iso_now()} {msg}"
    print(line, flush=True)
    path = log_path or LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sf(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    if pd.isna(x):
        return None
    return x


def _ts_iso(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("+00:00"):
            return s.replace("+00:00", "Z")
        if "T" not in s and " " in s:
            return s.replace(" ", "T") + ("Z" if not s.endswith("Z") else "")
        return s
    ts = pd.Timestamp(v)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def audit_imports(path: Path) -> dict[str, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exchange = False
    fit = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                    exchange = True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                exchange = True
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name.lower() in {"fit", "retrain", "train_model"}:
                fit = True
    return {
        "exchange_api_import_absent": not exchange,
        "model_fit_call_absent": not fit,
    }


def make_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def compute_stop_take(side: str, entry: float) -> tuple[float, float]:
    if side == "LONG":
        stop = entry * (1.0 - STOP_LOSS_BPS / 10000.0)
        take = entry * (1.0 + TAKE_PROFIT_BPS / 10000.0)
    elif side == "SHORT":
        stop = entry * (1.0 + STOP_LOSS_BPS / 10000.0)
        take = entry * (1.0 - TAKE_PROFIT_BPS / 10000.0)
    else:
        raise ValueError(f"unsupported_side:{side}")
    return float(stop), float(take)


def evaluate_exit_preview(
    *,
    side: str,
    entry_price: float,
    quantity: float,
    stop_loss_price: float,
    take_profit_price: float,
    entry_fee_usd: float,
    current_price: float,
    latest_high: float,
    latest_low: float,
    latest_context: str,
    latest_lifecycle_state: str,
) -> dict[str, Any]:
    side_u = str(side).upper()
    ctx = str(latest_context or "")
    life = str(latest_lifecycle_state or "").upper()

    if side_u == "LONG":
        unrealized_pnl_bps = ((current_price - entry_price) / entry_price) * 10000.0
        unrealized_pnl_usd = quantity * (current_price - entry_price)
        stop_loss_hit = latest_low <= stop_loss_price
        take_profit_hit = latest_high >= take_profit_price
        context_exit = ctx != "LONG_CONTEXT" or life in CONTEXT_EXIT_LIFECYCLES
        hold_action = "PREVIEW_HOLD_LONG"
        stop_action = "PREVIEW_CLOSE_LONG_STOP_LOSS"
        take_action = "PREVIEW_CLOSE_LONG_TAKE_PROFIT"
        ctx_action = "PREVIEW_CLOSE_LONG_CONTEXT_EXIT"
    elif side_u == "SHORT":
        unrealized_pnl_bps = ((entry_price - current_price) / entry_price) * 10000.0
        unrealized_pnl_usd = quantity * (entry_price - current_price)
        stop_loss_hit = latest_high >= stop_loss_price
        take_profit_hit = latest_low <= take_profit_price
        context_exit = ctx != "SHORT_CONTEXT" or life in CONTEXT_EXIT_LIFECYCLES
        hold_action = "PREVIEW_HOLD_SHORT"
        stop_action = "PREVIEW_CLOSE_SHORT_STOP_LOSS"
        take_action = "PREVIEW_CLOSE_SHORT_TAKE_PROFIT"
        ctx_action = "PREVIEW_CLOSE_SHORT_CONTEXT_EXIT"
    else:
        raise ValueError(f"unsupported_side:{side}")

    same_bar = bool(stop_loss_hit and take_profit_hit)
    if same_bar:
        action, reason = stop_action, "SAME_BAR_STOP_AND_TAKE_CONSERVATIVE_STOP_FIRST"
    elif stop_loss_hit:
        action, reason = stop_action, "STOP_LOSS_HIT"
    elif take_profit_hit:
        action, reason = take_action, "TAKE_PROFIT_HIT"
    elif context_exit:
        action, reason = (
            ctx_action,
            f"CONTEXT_OR_LIFECYCLE_EXIT:{ctx}/{life or 'UNKNOWN'}",
        )
    else:
        action, reason = hold_action, "NO_STOP_TAKE_OR_CONTEXT_EXIT_TRIGGER"

    exit_price = current_price
    if "STOP_LOSS" in action:
        exit_price = float(stop_loss_price)
    elif "TAKE_PROFIT" in action:
        exit_price = float(take_profit_price)

    return {
        "unrealized_pnl_bps": float(unrealized_pnl_bps),
        "unrealized_pnl_usd": float(unrealized_pnl_usd),
        "net_unrealized_after_entry_fee_usd": float(unrealized_pnl_usd - entry_fee_usd),
        "stop_loss_hit": bool(stop_loss_hit),
        "take_profit_hit": bool(take_profit_hit),
        "same_bar_stop_take_hit": same_bar,
        "context_exit_preview": bool(context_exit),
        "exit_preview_action": action,
        "exit_preview_reason": reason,
        "suggested_exit_price": float(exit_price),
        "is_hold": action.startswith("PREVIEW_HOLD_"),
        "is_close": action.startswith("PREVIEW_CLOSE_"),
    }


def evaluate_flat_entry_gate(decision: dict[str, Any]) -> dict[str, Any]:
    stale = bool(decision.get("decision_stale") or decision.get("stale_flag"))
    ctx = str(decision.get("active_market_context") or decision.get("context") or "")
    life = str(decision.get("lifecycle_state") or "")
    edge = _sf(decision.get("expected_edge_bps"))
    conf = _sf(decision.get("confidence"))
    reasons: list[str] = []
    if stale:
        reasons.append("stale_true")
    if ctx not in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        reasons.append(f"context_not_directional:{ctx}")
    if life.upper() not in {"ACTIVE", "CHALLENGED"}:
        reasons.append(f"lifecycle_not_tradable:{life}")
    if edge is None or edge <= 0:
        reasons.append("expected_edge_bps_not_positive")
    if conf is None:
        reasons.append("confidence_missing")
    ok = not reasons
    side = "LONG" if ctx == "LONG_CONTEXT" else ("SHORT" if ctx == "SHORT_CONTEXT" else None)
    return {
        "allowed": ok,
        "block_reasons": reasons,
        "side": side,
        "policy_action": f"OPEN_{side}" if side else "NO_TRADE",
        "paper_action": f"INTENT_OPEN_{side}" if side else "NO_SIGNAL",
    }


def ledger_counts(research: Path) -> dict[str, int]:
    mapping = {
        "paper_signals": "paper_signals.parquet",
        "paper_orders": "paper_orders.parquet",
        "paper_events": "paper_events.parquet",
        "paper_trades": "paper_trades.parquet",
        "paper_positions": "paper_positions.parquet",
        "paper_equity_rows": "paper_equity_curve.parquet",
        "paper_risk_blocks": "paper_risk_blocks.parquet",
    }
    out: dict[str, int] = {}
    for key, name in mapping.items():
        path = research / name
        out[key] = int(len(pd.read_parquet(path))) if path.exists() else 0
    return out


def load_open_positions(research: Path) -> list[dict[str, Any]]:
    path = research / "paper_positions.parquet"
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    if df.empty:
        return []
    opens = df[df["status"].astype(str) == "OPEN"]
    rows: list[dict[str, Any]] = []
    for _, r in opens.iterrows():
        d = r.to_dict()
        meta = _parse_meta(d.get("metadata_json"))
        rows.append(
            {
                "position_id": str(d.get("position_id")),
                "side": str(meta.get("side") or d.get("direction") or ""),
                "entry_price": float(d.get("entry_price")),
                "quantity_btc": float(meta.get("quantity_btc") or d.get("quantity") or 0.0),
                "notional_usd": float(meta.get("notional_usd") or d.get("notional") or 0.0),
                "stop_loss_price": float(
                    meta.get("stop_loss_price")
                    or compute_stop_take(str(meta.get("side") or d.get("direction")), float(d.get("entry_price")))[0]
                ),
                "take_profit_price": float(
                    meta.get("take_profit_price")
                    or compute_stop_take(str(meta.get("side") or d.get("direction")), float(d.get("entry_price")))[1]
                ),
                "entry_fee_usd": float(meta.get("entry_fee_usd") or d.get("fees_paid") or 0.0),
                "opened_at": str(d.get("opened_at") or ""),
                "opening_decision_id": str(d.get("opening_decision_id") or ""),
                "parent_trade_id": str(meta.get("parent_trade_id") or ""),
                "parent_order_id": str(meta.get("parent_order_id") or ""),
                "parent_signal_id": str(meta.get("parent_signal_id") or ""),
                "symbol": str(d.get("symbol") or "BTCUSDT"),
                "raw": d,
                "meta": meta,
            }
        )
    return rows


def load_latest_market(live: Path) -> dict[str, Any]:
    feed = pd.read_parquet(live / "live_market_feed.parquet").sort_values("timestamp")
    row = feed.iloc[-1]
    return {
        "latest_market_ts": _ts_iso(row["timestamp"]),
        "latest_open": float(row["open"]),
        "latest_high": float(row["high"]),
        "latest_low": float(row["low"]),
        "latest_close": float(row["close"]),
        "current_price": float(row["close"]),
    }


def load_latest_decision(live: Path) -> dict[str, Any]:
    log = pd.read_parquet(live / "context_decision_log.parquet")
    if log.empty:
        return {}
    tmp = log.copy()
    tmp["_ts"] = pd.to_datetime(tmp["candle_timestamp"], utc=True, errors="coerce")
    tmp = tmp.sort_values("_ts")
    row = tmp.iloc[-1].to_dict()
    row["latest_decision_log_ts"] = _ts_iso(row.get("candle_timestamp"))
    return row


def live_close_at_ts(live: Path, ts: str) -> float | None:
    feed = pd.read_parquet(live / "live_market_feed.parquet")
    if feed.empty:
        return None
    feed = feed.copy()
    feed["_ts"] = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
    target = pd.Timestamp(ts)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    else:
        target = target.tz_convert("UTC")
    hit = feed[feed["_ts"] == target]
    if hit.empty:
        # fallback: latest closed close
        return float(feed.sort_values("_ts").iloc[-1]["close"])
    px = float(hit.iloc[-1]["close"])
    if abs(px - SYNTHETIC_FORBIDDEN_PRICE) < 1e-9:
        return None
    return px


def _append_row(path: Path, columns: list[str], record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame([{c: record.get(c) for c in columns}], columns=columns)
    if path.exists():
        old = pd.read_parquet(path)
        for c in columns:
            if c not in old.columns:
                old[c] = None
        out = pd.concat([old, new_df], ignore_index=True)
    else:
        out = new_df
    out.to_parquet(path, index=False)


def _ids_exist(research: Path, *, signal_id: str | None = None, order_id: str | None = None, trade_id: str | None = None, position_id: str | None = None) -> list[str]:
    dup: list[str] = []
    if signal_id and (research / "paper_signals.parquet").exists():
        df = pd.read_parquet(research / "paper_signals.parquet")
        if (df["signal_id"].astype(str) == signal_id).any():
            dup.append("signal_id")
    if order_id and (research / "paper_orders.parquet").exists():
        df = pd.read_parquet(research / "paper_orders.parquet")
        if (df["paper_order_id"].astype(str) == order_id).any():
            dup.append("order_id")
    if trade_id and (research / "paper_trades.parquet").exists():
        df = pd.read_parquet(research / "paper_trades.parquet")
        if (df["paper_trade_id"].astype(str) == trade_id).any():
            dup.append("trade_id")
    if position_id and (research / "paper_positions.parquet").exists():
        df = pd.read_parquet(research / "paper_positions.parquet")
        if (df["position_id"].astype(str) == position_id).any():
            dup.append("position_id")
    return dup


def write_open_position_chain(
    *,
    research: Path,
    decision: dict[str, Any],
    side: str,
    entry_price: float,
    entry_price_source: str,
    market_ts: str,
) -> dict[str, Any]:
    if abs(entry_price - SYNTHETIC_FORBIDDEN_PRICE) < 1e-9:
        raise RuntimeError("synthetic_price_forbidden")
    stop, take = compute_stop_take(side, entry_price)
    qty = PAPER_NOTIONAL / entry_price
    fee = PAPER_NOTIONAL * ENTRY_FEE_BPS / 10000.0
    now = _iso_now()
    decision_ts = _ts_iso(decision.get("candle_timestamp") or decision.get("latest_decision_log_ts"))
    source_ts = decision_ts
    order_side = "BUY" if side == "LONG" else "SELL"
    position_effect = f"OPEN_{side}"
    conf = _sf(decision.get("confidence"))
    edge = _sf(decision.get("expected_edge_bps"))

    signal_id = make_id(
        "PAPER_SIGNAL_CTRL",
        decision_ts,
        side,
        f"{entry_price:.8f}",
        "OPEN",
    )
    order_id = make_id("PAPER_ORDER_CTRL", signal_id, side, f"{entry_price:.8f}")
    trade_id = make_id("PAPER_TRADE_CTRL", order_id, signal_id, side, f"{entry_price:.8f}")
    position_id = make_id("PAPER_POSITION_CTRL", trade_id, order_id, side)
    equity_id = make_id("PAPER_EQUITY_CTRL", trade_id, position_id, "ENTRY")
    event_id = make_id("PAPER_EVENT_CTRL", trade_id, "OPEN")

    dups = _ids_exist(
        research,
        signal_id=signal_id,
        order_id=order_id,
        trade_id=trade_id,
        position_id=position_id,
    )
    if dups:
        raise RuntimeError(f"duplicate_ids:{','.join(dups)}")

    signal = {
        "signal_id": signal_id,
        "signal_status": "CONTROLLER_AUTO",
        "signal_source": "BOUNDED_PAPER_CONTROLLER",
        "decision_log_ts": decision_ts,
        "source_context_ts": source_ts,
        "context": decision.get("active_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "stale_flag": bool(decision.get("decision_stale")),
        "side": side,
        "policy_action": f"OPEN_{side}",
        "paper_action": f"INTENT_OPEN_{side}",
        "paper_intent": position_effect,
        "order_side": order_side,
        "position_effect": position_effect,
        "entry_price_source": entry_price_source,
        "entry_price": entry_price,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "stop_loss_bps": STOP_LOSS_BPS,
        "take_profit_bps": TAKE_PROFIT_BPS,
        "expected_edge_bps": edge,
        "confidence": conf,
        "cost_model_bps": COST_MODEL_BPS,
        "lookup_applied": bool(decision.get("lookup_applied")),
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
    }
    order = {
        "paper_order_id": order_id,
        "created_at": now,
        "decision_id": signal_id,
        "candle_timestamp": decision_ts,
        "symbol": "BTCUSDT",
        "side": order_side,
        "order_type": "MARKET",
        "quantity": qty,
        "requested_price": entry_price,
        "notional": PAPER_NOTIONAL,
        "status": "FILLED",
        "fill_price": entry_price,
        "filled_quantity": qty,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": 0.0,
        "paper_only": True,
        "execution_enabled": False,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "metadata_json": json.dumps(
            {
                "parent_signal_id": signal_id,
                "side": side,
                "order_side": order_side,
                "position_effect": position_effect,
                "intended_entry_price": entry_price,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "entry_price_source": entry_price_source,
                "market_ts": market_ts,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    trade = {
        "paper_trade_id": trade_id,
        "paper_order_id": order_id,
        "position_id": position_id,
        "timestamp": now,
        "symbol": "BTCUSDT",
        "side": order_side,
        "quantity": qty,
        "price": entry_price,
        "notional": PAPER_NOTIONAL,
        "fee": fee,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage": 0.0,
        "slippage_bps": 0.0,
        "realized_pnl": 0.0,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": json.dumps(
            {
                "trade_type": "ENTRY",
                "parent_signal_id": signal_id,
                "side": side,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    position = {
        "position_id": position_id,
        "opened_at": now,
        "closed_at": None,
        "symbol": "BTCUSDT",
        "direction": side,
        "quantity": qty,
        "entry_price": entry_price,
        "exit_price": None,
        "notional": PAPER_NOTIONAL,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": fee,
        "slippage_paid": 0.0,
        "status": "OPEN",
        "opening_decision_id": signal_id,
        "closing_decision_id": None,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": json.dumps(
            {
                "paper_position_id": position_id,
                "parent_trade_id": trade_id,
                "parent_order_id": order_id,
                "parent_signal_id": signal_id,
                "position_status": "OPEN",
                "side": side,
                "quantity_btc": qty,
                "notional_usd": PAPER_NOTIONAL,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "stop_loss_bps": STOP_LOSS_BPS,
                "take_profit_bps": TAKE_PROFIT_BPS,
                "entry_fee_usd": fee,
                "entry_price_source": entry_price_source,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    equity_after = PAPER_INITIAL_EQUITY - fee
    # Prefer last equity cash if present
    eq_path = research / "paper_equity_curve.parquet"
    if eq_path.exists():
        eq = pd.read_parquet(eq_path)
        if not eq.empty:
            last_eq = float(eq.iloc[-1]["equity"])
            equity_after = last_eq - fee
    equity = {
        "timestamp": now,
        "cash": equity_after,
        "position_value": PAPER_NOTIONAL,
        "equity": equity_after,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": fee,
        "slippage_paid": 0.0,
        "drawdown_pct": 0.0,
        "daily_pnl": -fee,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": json.dumps(
            {
                "paper_equity_snapshot_id": equity_id,
                "equity_snapshot_type": "PAPER_ENTRY_SNAPSHOT",
                "linked_trade_id": trade_id,
                "linked_position_id": position_id,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    event = {
        "event_id": event_id,
        "event_type": "PAPER_POSITION_OPENED",
        "timestamp": now,
        "decision_id": signal_id,
        "candle_timestamp": decision_ts,
        "active_market_context": decision.get("active_market_context"),
        "raw_market_context": decision.get("raw_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "candidate_model_version": None,
        "candidate_prediction_label": None,
        "signal_direction": side,
        "paper_action": f"INTENT_OPEN_{side}",
        "action_reason": "CONTROLLER_AUTO_OPEN",
        "paper_order_id": order_id,
        "position_id": position_id,
        "symbol": "BTCUSDT",
        "price": entry_price,
        "quantity": qty,
        "notional": PAPER_NOTIONAL,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": 0.0,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "execution_enabled": False,
        "paper_only": True,
        "metadata_json": json.dumps({"approval_phrase": APPROVAL_PHRASE}),
    }

    _append_row(research / "paper_signals.parquet", SIGNAL_COLUMNS, signal)
    _append_row(research / "paper_orders.parquet", ORDER_COLUMNS, order)
    _append_row(research / "paper_trades.parquet", TRADE_COLUMNS, trade)
    _append_row(research / "paper_positions.parquet", POSITION_COLUMNS, position)
    _append_row(research / "paper_equity_curve.parquet", EQUITY_COLUMNS, equity)
    _append_row(research / "paper_events.parquet", EVENT_COLUMNS, event)

    return {
        "signal_id": signal_id,
        "order_id": order_id,
        "trade_id": trade_id,
        "position_id": position_id,
        "equity_id": equity_id,
        "entry_price": entry_price,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "quantity_btc": qty,
        "paper_ledger_write_performed": True,
        "new_signal_written": True,
        "new_order_written": True,
        "new_trade_written": True,
        "position_update_written": True,
        "equity_update_written": True,
    }


def write_close_position_chain(
    *,
    research: Path,
    open_pos: dict[str, Any],
    exit_preview: dict[str, Any],
    decision: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any]:
    now = _iso_now()
    side = open_pos["side"]
    entry = float(open_pos["entry_price"])
    qty = float(open_pos["quantity_btc"])
    exit_price = float(exit_preview["suggested_exit_price"])
    if abs(exit_price - SYNTHETIC_FORBIDDEN_PRICE) < 1e-9:
        raise RuntimeError("synthetic_exit_price_forbidden")

    if side == "LONG":
        realized = qty * (exit_price - entry)
        order_side = "SELL"
    else:
        realized = qty * (entry - exit_price)
        order_side = "BUY"
    exit_fee = (qty * exit_price) * ENTRY_FEE_BPS / 10000.0
    realized_after_exit_fee = realized - exit_fee
    decision_ts = _ts_iso(decision.get("candle_timestamp") or decision.get("latest_decision_log_ts"))
    reason = str(exit_preview["exit_preview_reason"])
    action = str(exit_preview["exit_preview_action"])

    close_signal_id = make_id(
        "PAPER_SIGNAL_CTRL",
        open_pos["position_id"],
        action,
        decision_ts,
        f"{exit_price:.8f}",
    )
    close_order_id = make_id("PAPER_ORDER_CTRL", close_signal_id, "CLOSE", f"{exit_price:.8f}")
    close_trade_id = make_id(
        "PAPER_TRADE_CTRL",
        close_order_id,
        open_pos["position_id"],
        "CLOSE",
        f"{exit_price:.8f}",
    )
    equity_id = make_id("PAPER_EQUITY_CTRL", close_trade_id, open_pos["position_id"], "CLOSE")
    event_id = make_id("PAPER_EVENT_CTRL", close_trade_id, "CLOSE")

    dups = _ids_exist(
        research,
        signal_id=close_signal_id,
        order_id=close_order_id,
        trade_id=close_trade_id,
    )
    if dups:
        raise RuntimeError(f"duplicate_close_ids:{','.join(dups)}")

    signal = {
        "signal_id": close_signal_id,
        "signal_status": "CONTROLLER_AUTO",
        "signal_source": "BOUNDED_PAPER_CONTROLLER",
        "decision_log_ts": decision_ts,
        "source_context_ts": decision_ts,
        "context": decision.get("active_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "stale_flag": bool(decision.get("decision_stale")),
        "side": side,
        "policy_action": action.replace("PREVIEW_", ""),
        "paper_action": f"INTENT_CLOSE_{side}",
        "paper_intent": f"CLOSE_{side}",
        "order_side": order_side,
        "position_effect": f"CLOSE_{side}",
        "entry_price_source": "LIVE_CLOSE_OR_STOP_TAKE",
        "entry_price": exit_price,
        "stop_loss_price": open_pos["stop_loss_price"],
        "take_profit_price": open_pos["take_profit_price"],
        "stop_loss_bps": STOP_LOSS_BPS,
        "take_profit_bps": TAKE_PROFIT_BPS,
        "expected_edge_bps": _sf(decision.get("expected_edge_bps")),
        "confidence": _sf(decision.get("confidence")),
        "cost_model_bps": COST_MODEL_BPS,
        "lookup_applied": bool(decision.get("lookup_applied")),
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
    }
    notional = qty * exit_price
    order = {
        "paper_order_id": close_order_id,
        "created_at": now,
        "decision_id": close_signal_id,
        "candle_timestamp": decision_ts,
        "symbol": open_pos["symbol"],
        "side": order_side,
        "order_type": "MARKET",
        "quantity": qty,
        "requested_price": exit_price,
        "notional": notional,
        "status": "FILLED",
        "fill_price": exit_price,
        "filled_quantity": qty,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": 0.0,
        "paper_only": True,
        "execution_enabled": False,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "metadata_json": json.dumps(
            {
                "parent_signal_id": close_signal_id,
                "close_of_position_id": open_pos["position_id"],
                "exit_preview_action": action,
                "exit_reason": reason,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    trade = {
        "paper_trade_id": close_trade_id,
        "paper_order_id": close_order_id,
        "position_id": open_pos["position_id"],
        "timestamp": now,
        "symbol": open_pos["symbol"],
        "side": order_side,
        "quantity": qty,
        "price": exit_price,
        "notional": notional,
        "fee": exit_fee,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage": 0.0,
        "slippage_bps": 0.0,
        "realized_pnl": realized_after_exit_fee,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": json.dumps(
            {
                "trade_type": "EXIT",
                "exit_preview_action": action,
                "exit_reason": reason,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }

    # Update position row in place
    pos_path = research / "paper_positions.parquet"
    pos_df = pd.read_parquet(pos_path)
    idx = pos_df.index[pos_df["position_id"].astype(str) == open_pos["position_id"]]
    if len(idx) == 0:
        raise RuntimeError("open_position_row_missing")
    i = int(idx[-1])
    meta = _parse_meta(pos_df.at[i, "metadata_json"])
    meta.update(
        {
            "position_status": "CLOSED",
            "exit_price": exit_price,
            "exit_reason": reason,
            "exit_preview_action": action,
            "realized_pnl_usd": realized_after_exit_fee,
            "closed_at": now,
            "approval_phrase": APPROVAL_PHRASE,
        }
    )
    pos_df.at[i, "closed_at"] = now
    pos_df.at[i, "exit_price"] = exit_price
    pos_df.at[i, "realized_pnl"] = realized_after_exit_fee
    pos_df.at[i, "unrealized_pnl"] = 0.0
    pos_df.at[i, "fees_paid"] = float(pos_df.at[i, "fees_paid"] or 0.0) + exit_fee
    pos_df.at[i, "status"] = "CLOSED"
    pos_df.at[i, "closing_decision_id"] = close_signal_id
    pos_df.at[i, "execution_enabled"] = False
    pos_df.at[i, "metadata_json"] = json.dumps(meta)

    last_equity = PAPER_INITIAL_EQUITY
    eq_path = research / "paper_equity_curve.parquet"
    if eq_path.exists():
        eq = pd.read_parquet(eq_path)
        if not eq.empty:
            last_equity = float(eq.iloc[-1]["equity"])
    new_equity = last_equity + realized_after_exit_fee
    equity = {
        "timestamp": now,
        "cash": new_equity,
        "position_value": 0.0,
        "equity": new_equity,
        "realized_pnl": realized_after_exit_fee,
        "unrealized_pnl": 0.0,
        "fees_paid": exit_fee,
        "slippage_paid": 0.0,
        "drawdown_pct": 0.0,
        "daily_pnl": realized_after_exit_fee,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": json.dumps(
            {
                "paper_equity_snapshot_id": equity_id,
                "equity_snapshot_type": "PAPER_EXIT_SNAPSHOT",
                "linked_trade_id": close_trade_id,
                "linked_position_id": open_pos["position_id"],
                "exit_preview_action": action,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    event = {
        "event_id": event_id,
        "event_type": "PAPER_POSITION_CLOSED",
        "timestamp": now,
        "decision_id": close_signal_id,
        "candle_timestamp": decision_ts,
        "active_market_context": decision.get("active_market_context"),
        "raw_market_context": decision.get("raw_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "candidate_model_version": None,
        "candidate_prediction_label": None,
        "signal_direction": side,
        "paper_action": f"INTENT_CLOSE_{side}",
        "action_reason": reason,
        "paper_order_id": close_order_id,
        "position_id": open_pos["position_id"],
        "symbol": open_pos["symbol"],
        "price": exit_price,
        "quantity": qty,
        "notional": notional,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": 0.0,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "execution_enabled": False,
        "paper_only": True,
        "metadata_json": json.dumps(
            {"exit_preview_action": action, "approval_phrase": APPROVAL_PHRASE}
        ),
    }

    _append_row(research / "paper_signals.parquet", SIGNAL_COLUMNS, signal)
    _append_row(research / "paper_orders.parquet", ORDER_COLUMNS, order)
    _append_row(research / "paper_trades.parquet", TRADE_COLUMNS, trade)
    pos_df.to_parquet(pos_path, index=False)
    _append_row(research / "paper_equity_curve.parquet", EQUITY_COLUMNS, equity)
    _append_row(research / "paper_events.parquet", EVENT_COLUMNS, event)

    return {
        "signal_id": close_signal_id,
        "order_id": close_order_id,
        "trade_id": close_trade_id,
        "position_id": open_pos["position_id"],
        "equity_id": equity_id,
        "exit_price": exit_price,
        "pnl_usd": realized_after_exit_fee,
        "pnl_bps": ((exit_price - entry) / entry) * 10000.0
        if side == "LONG"
        else ((entry - exit_price) / entry) * 10000.0,
        "paper_ledger_write_performed": True,
        "new_signal_written": True,
        "new_order_written": True,
        "new_trade_written": True,
        "position_update_written": True,
        "equity_update_written": True,
    }


def safety_preflight(
    *,
    research: Path,
    paper_only: bool,
    no_real_execution: bool,
    this_path: Path,
) -> dict[str, Any]:
    imports = audit_imports(this_path)
    opens = load_open_positions(research)
    checks = {
        "paper_only": paper_only is True,
        "no_real_execution": no_real_execution is True,
        "execution_enabled_false": True,
        "exchange_import_absent": imports["exchange_api_import_absent"],
        "model_fit_absent": imports["model_fit_call_absent"],
        "open_positions_le_one": len(opens) <= 1,
        "controller_mode_paper_only": CONTROLLER_MODE == "PAPER_ONLY",
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "open_position_count": len(opens),
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "paper_only_mode": True,
    }


def refresh_and_maybe_append(
    *,
    root: Path,
    skip_refresh: bool,
) -> dict[str, Any]:
    if skip_refresh:
        return {
            "refresh_performed": False,
            "decision_log_append_performed": False,
            "appended_rows_count": 0,
            "skipped": True,
        }

    refresh_mod = _load_module(
        "run_live_context_refresh_once_ctrl",
        root / "scripts" / "live" / "run_live_context_refresh_once.py",
    )
    logger_mod = _load_module(
        "append_context_decision_log_ctrl",
        root / "scripts" / "live" / "append_context_decision_log.py",
    )
    single_mod = _load_module(
        "single_live_refresh_append_ctrl",
        root
        / "scripts"
        / "live"
        / "single_live_context_refresh_and_decision_log_append_no_paper_signal.py",
    )

    live_feed = root / "data" / "live" / "live_market_feed.parquet"
    lifecycle = root / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    shadow = root / "scripts" / "research" / "build_market_context_shadow_chain.py"
    decision_log = root / "data" / "live" / "context_decision_log.parquet"

    refresh_result = single_mod.run_one_shot_refresh(
        live_feed=live_feed,
        lifecycle_path=lifecycle,
        shadow_script=shadow,
        refresh_mod=refresh_mod,
    )
    if refresh_result.get("refresh_status") != "OK":
        return {
            "refresh_performed": True,
            "decision_log_append_performed": False,
            "appended_rows_count": 0,
            "error": refresh_result.get("error"),
            "refresh_result": refresh_result,
        }

    auction = root / "data" / "cognition" / "auction_episode_memory.parquet"
    cognitive = root / "data" / "cognition" / "cognitive_market_state_memory.parquet"
    final = root / "data" / "cognition" / "final_market_context_memory.parquet"
    runtime_log = root / "logs" / "runtime_stack" / "runtime.log"
    if not runtime_log.exists():
        runtime_log = root / "logs" / "runtime.log"
    corrected_lookup = (
        root
        / "data"
        / "research"
        / "paper_simulator"
        / "corrected_lagged_context_edge_lookup_snapshot.parquet"
    )
    row, _preview, _enrich = single_mod.build_decision_preview(
        logger_mod=logger_mod,
        live_feed=live_feed,
        auction_path=auction,
        cognitive_path=cognitive,
        final_path=final,
        lifecycle_path=lifecycle,
        runtime_log=runtime_log,
        corrected_lookup=corrected_lookup,
    )
    # Force paper/execution safety on decision row
    row["execution_enabled"] = False
    row["paper_signal_write_allowed"] = False
    row["paper_loop_allowed"] = False

    guards = single_mod.check_append_guards(
        logger_mod=logger_mod, row=row, decision_log=decision_log
    )
    if not guards.get("allowed"):
        return {
            "refresh_performed": True,
            "decision_log_append_performed": False,
            "appended_rows_count": 0,
            "append_blocked": guards.get("block_status"),
            "refresh_result": refresh_result,
        }

    append_result = logger_mod.append_decision(row, log_path=decision_log)
    return {
        "refresh_performed": True,
        "decision_log_append_performed": True,
        "appended_rows_count": 1,
        "append_result": append_result,
        "refresh_result": refresh_result,
    }


def append_cycle_record(research: Path, record: dict[str, Any]) -> None:
    path = research / "bounded_paper_controller_cycles.parquet"
    _append_row(path, CYCLE_COLUMNS, {c: record.get(c) for c in CYCLE_COLUMNS})
    csv_path = research / "bounded_paper_controller_cycles.csv"
    df = pd.read_parquet(path)
    df.to_csv(csv_path, index=False)


def append_action_record(research: Path, record: dict[str, Any]) -> None:
    path = research / "bounded_paper_controller_actions.parquet"
    _append_row(path, ACTION_COLUMNS, {c: record.get(c) for c in ACTION_COLUMNS})
    csv_path = research / "bounded_paper_controller_actions.csv"
    df = pd.read_parquet(path)
    df.to_csv(csv_path, index=False)


def run_one_cycle(
    *,
    root: Path,
    cycle_idx: int,
    skip_refresh: bool = False,
    allow_open: bool = True,
) -> dict[str, Any]:
    research = root / "data" / "research" / "paper_simulator"
    live = root / "data" / "live"
    this_path = Path(__file__).resolve()
    cycle_id = f"CYCLE_{cycle_idx:04d}_{int(time.time())}"
    cycle_ts = _iso_now()

    pre = safety_preflight(
        research=research,
        paper_only=True,
        no_real_execution=True,
        this_path=this_path,
    )
    if not pre["ok"]:
        out = {
            "cycle_id": cycle_id,
            "cycle_ts": cycle_ts,
            "cycle_status": "STOPPED_SAFETY_PREFLIGHT",
            "action_taken": "STOP",
            "reason": "safety_preflight_failed",
            "preflight": pre,
            "paper_ledger_write_performed": False,
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "stop_controller": True,
        }
        append_cycle_record(
            research,
            {
                "cycle_id": cycle_id,
                "cycle_ts": cycle_ts,
                "market_ts": None,
                "decision_log_ts": None,
                "context": None,
                "lifecycle_state": None,
                "position_state_before": None,
                "action_taken": "STOP",
                "signal_id": None,
                "order_id": None,
                "trade_id": None,
                "position_id": None,
                "equity_id": None,
                "entry_price": None,
                "exit_price": None,
                "pnl_bps": None,
                "pnl_usd": None,
                "reason": "safety_preflight_failed",
                "exit_preview_action": None,
                "paper_ledger_write_performed": False,
                "execution_enabled": False,
                "exchange_api_call_used": False,
                "cycle_status": "STOPPED_SAFETY_PREFLIGHT",
            },
        )
        return out

    refresh_info = refresh_and_maybe_append(root=root, skip_refresh=skip_refresh)
    if refresh_info.get("error"):
        out = {
            "cycle_id": cycle_id,
            "cycle_ts": cycle_ts,
            "cycle_status": "ERROR_REFRESH",
            "action_taken": "STOP",
            "reason": refresh_info.get("error"),
            "refresh": refresh_info,
            "paper_ledger_write_performed": False,
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "stop_controller": True,
        }
        append_cycle_record(
            research,
            {
                "cycle_id": cycle_id,
                "cycle_ts": cycle_ts,
                "market_ts": None,
                "decision_log_ts": None,
                "context": None,
                "lifecycle_state": None,
                "position_state_before": None,
                "action_taken": "STOP",
                "signal_id": None,
                "order_id": None,
                "trade_id": None,
                "position_id": None,
                "equity_id": None,
                "entry_price": None,
                "exit_price": None,
                "pnl_bps": None,
                "pnl_usd": None,
                "reason": str(refresh_info.get("error")),
                "exit_preview_action": None,
                "paper_ledger_write_performed": False,
                "execution_enabled": False,
                "exchange_api_call_used": False,
                "cycle_status": "ERROR_REFRESH",
            },
        )
        return out

    market = load_latest_market(live)
    decision = load_latest_decision(live)
    opens = load_open_positions(research)
    if len(opens) > 1:
        out = {
            "cycle_id": cycle_id,
            "cycle_ts": cycle_ts,
            "cycle_status": "STOPPED_MULTI_OPEN",
            "action_taken": "STOP",
            "reason": "more_than_one_open_position",
            "open_position_count": len(opens),
            "paper_ledger_write_performed": False,
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "stop_controller": True,
        }
        append_cycle_record(
            research,
            {
                "cycle_id": cycle_id,
                "cycle_ts": cycle_ts,
                "market_ts": market.get("latest_market_ts"),
                "decision_log_ts": decision.get("latest_decision_log_ts"),
                "context": decision.get("active_market_context"),
                "lifecycle_state": decision.get("lifecycle_state"),
                "position_state_before": "MULTI_OPEN",
                "action_taken": "STOP",
                "signal_id": None,
                "order_id": None,
                "trade_id": None,
                "position_id": None,
                "equity_id": None,
                "entry_price": None,
                "exit_price": None,
                "pnl_bps": None,
                "pnl_usd": None,
                "reason": "more_than_one_open_position",
                "exit_preview_action": None,
                "paper_ledger_write_performed": False,
                "execution_enabled": False,
                "exchange_api_call_used": False,
                "cycle_status": "STOPPED_MULTI_OPEN",
            },
        )
        return out

    result: dict[str, Any] = {
        "cycle_id": cycle_id,
        "cycle_ts": cycle_ts,
        "cycle_status": "OK",
        "latest_market_ts": market["latest_market_ts"],
        "latest_decision_log_ts": decision.get("latest_decision_log_ts"),
        "latest_context": decision.get("active_market_context"),
        "latest_lifecycle_state": decision.get("lifecycle_state"),
        "position_state_before": "FLAT" if not opens else opens[0]["side"],
        "action_taken": "OBSERVE",
        "exit_preview_action": None,
        "paper_ledger_write_performed": False,
        "new_signal_written": False,
        "new_order_written": False,
        "new_trade_written": False,
        "position_update_written": False,
        "equity_update_written": False,
        "signal_id": None,
        "order_id": None,
        "trade_id": None,
        "position_id": None,
        "equity_id": None,
        "entry_price": None,
        "exit_price": None,
        "pnl_bps": None,
        "pnl_usd": None,
        "reason": None,
        "refresh": refresh_info,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "stop_controller": False,
    }

    if opens:
        pos = opens[0]
        exit_preview = evaluate_exit_preview(
            side=pos["side"],
            entry_price=pos["entry_price"],
            quantity=pos["quantity_btc"],
            stop_loss_price=pos["stop_loss_price"],
            take_profit_price=pos["take_profit_price"],
            entry_fee_usd=pos["entry_fee_usd"],
            current_price=market["current_price"],
            latest_high=market["latest_high"],
            latest_low=market["latest_low"],
            latest_context=str(decision.get("active_market_context") or ""),
            latest_lifecycle_state=str(decision.get("lifecycle_state") or ""),
        )
        result["exit_preview_action"] = exit_preview["exit_preview_action"]
        result["pnl_bps"] = exit_preview["unrealized_pnl_bps"]
        result["pnl_usd"] = exit_preview["unrealized_pnl_usd"]
        result["position_id"] = pos["position_id"]
        result["entry_price"] = pos["entry_price"]

        if exit_preview["is_hold"]:
            result["action_taken"] = "OBSERVE_HOLD"
            result["reason"] = exit_preview["exit_preview_reason"]
        else:
            written = write_close_position_chain(
                research=research,
                open_pos=pos,
                exit_preview=exit_preview,
                decision=decision,
                market=market,
            )
            result.update(
                {
                    "action_taken": "CLOSE_POSITION",
                    "reason": exit_preview["exit_preview_reason"],
                    **written,
                    "exit_price": written.get("exit_price"),
                    "pnl_bps": written.get("pnl_bps"),
                    "pnl_usd": written.get("pnl_usd"),
                }
            )
            append_action_record(
                research,
                {
                    "action_id": make_id("ACTION", cycle_id, "CLOSE"),
                    "cycle_id": cycle_id,
                    "action_ts": _iso_now(),
                    "action_type": "CLOSE",
                    "signal_id": written.get("signal_id"),
                    "order_id": written.get("order_id"),
                    "trade_id": written.get("trade_id"),
                    "position_id": written.get("position_id"),
                    "equity_id": written.get("equity_id"),
                    "side": pos["side"],
                    "price": written.get("exit_price"),
                    "reason": exit_preview["exit_preview_reason"],
                    "execution_enabled": False,
                },
            )
    else:
        gate = evaluate_flat_entry_gate(decision)
        if not allow_open or not gate["allowed"]:
            result["action_taken"] = "OBSERVE_NO_TRADE"
            result["reason"] = (
                "open_disabled"
                if not allow_open
                else ",".join(gate["block_reasons"]) or "no_trade"
            )
        else:
            side = str(gate["side"])
            px = live_close_at_ts(live, str(decision.get("candle_timestamp")))
            if px is None:
                result["action_taken"] = "OBSERVE_NO_TRADE"
                result["reason"] = "live_price_unavailable_or_synthetic"
            else:
                written = write_open_position_chain(
                    research=research,
                    decision=decision,
                    side=side,
                    entry_price=float(px),
                    entry_price_source="LIVE_CLOSE_AT_SOURCE_CONTEXT_TS",
                    market_ts=market["latest_market_ts"],
                )
                result.update(
                    {
                        "action_taken": f"OPEN_{side}",
                        "reason": "controller_auto_open",
                        **written,
                        "entry_price": written.get("entry_price"),
                        "position_id": written.get("position_id"),
                    }
                )
                append_action_record(
                    research,
                    {
                        "action_id": make_id("ACTION", cycle_id, "OPEN"),
                        "cycle_id": cycle_id,
                        "action_ts": _iso_now(),
                        "action_type": "OPEN",
                        "signal_id": written.get("signal_id"),
                        "order_id": written.get("order_id"),
                        "trade_id": written.get("trade_id"),
                        "position_id": written.get("position_id"),
                        "equity_id": written.get("equity_id"),
                        "side": side,
                        "price": written.get("entry_price"),
                        "reason": "controller_auto_open",
                        "execution_enabled": False,
                    },
                )

    append_cycle_record(
        research,
        {
            "cycle_id": cycle_id,
            "cycle_ts": cycle_ts,
            "market_ts": result.get("latest_market_ts"),
            "decision_log_ts": result.get("latest_decision_log_ts"),
            "context": result.get("latest_context"),
            "lifecycle_state": result.get("latest_lifecycle_state"),
            "position_state_before": result.get("position_state_before"),
            "action_taken": result.get("action_taken"),
            "signal_id": result.get("signal_id"),
            "order_id": result.get("order_id"),
            "trade_id": result.get("trade_id"),
            "position_id": result.get("position_id"),
            "equity_id": result.get("equity_id"),
            "entry_price": result.get("entry_price"),
            "exit_price": result.get("exit_price"),
            "pnl_bps": result.get("pnl_bps"),
            "pnl_usd": result.get("pnl_usd"),
            "reason": result.get("reason"),
            "exit_preview_action": result.get("exit_preview_action"),
            "paper_ledger_write_performed": bool(result.get("paper_ledger_write_performed")),
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "cycle_status": result.get("cycle_status"),
        },
    )
    return result


def write_status_bundle(
    *,
    research: Path,
    running: bool,
    pid: int | None,
    cycle_idx: int,
    max_cycles: int,
    interval_seconds: int,
    max_duration_hours: float,
    last_cycle: dict[str, Any] | None,
    stop_reason: str | None = None,
) -> None:
    opens = load_open_positions(research)
    counts = ledger_counts(research)
    open0 = opens[0] if opens else None
    status = {
        "generated_at_utc": _iso_now(),
        "controller_running": running,
        "pid": pid,
        "cycle_idx": cycle_idx,
        "max_cycles": max_cycles,
        "interval_seconds": interval_seconds,
        "max_duration_hours": max_duration_hours,
        "paper_only_mode": True,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "collecting_paper_data": True,
        "stop_reason": stop_reason,
        "last_cycle": last_cycle,
        "ledger_counts": counts,
        "open_position_count": len(opens),
        "open_position_id": None if open0 is None else open0["position_id"],
    }
    state = {
        "generated_at_utc": _iso_now(),
        "open_positions": [
            {
                "position_id": p["position_id"],
                "side": p["side"],
                "entry_price": p["entry_price"],
                "stop_loss_price": p["stop_loss_price"],
                "take_profit_price": p["take_profit_price"],
            }
            for p in opens
        ],
        "ledger_counts": counts,
        "last_cycle_id": None if last_cycle is None else last_cycle.get("cycle_id"),
    }
    safety = {
        "generated_at_utc": _iso_now(),
        "paper_only_mode": True,
        "exchange_api_call_used": False,
        "execution_enabled": False,
        "real_order_routing_enabled": False,
        "dashboard_started": False,
        "model_fit_used": False,
        "retraining_used": False,
        "bounded_loop": True,
        "safety_status": "PASS",
    }
    final = {
        "status": (
            "BOUNDED_PAPER_TRADING_CONTROLLER_RUNNING"
            if running
            else "BOUNDED_PAPER_TRADING_CONTROLLER_STOPPED"
        ),
        "qa_status": "PASS_WITH_LIMITATIONS",
        "controller_running": running,
        "collecting_paper_data": True,
        "execution_enabled": False,
        "run_readiness_status": (
            "CONTROLLER_COLLECTING_PAPER_DATASET"
            if running
            else "CONTROLLER_STOPPED"
        ),
        "next_recommended_step": (
            "MONITOR_BOUNDED_PAPER_CONTROLLER_STATUS"
            if running
            else "REVIEW_BOUNDED_PAPER_CONTROLLER_DATASET"
        ),
        "approval_phrase": APPROVAL_PHRASE,
        "generated_at_utc": _iso_now(),
        "stop_reason": stop_reason,
        "last_cycle": last_cycle,
    }
    _write_json(research / "bounded_paper_controller_status.json", status)
    _write_json(research / "bounded_paper_controller_state.json", state)
    _write_json(research / "bounded_paper_controller_safety.json", safety)
    _write_json(research / "bounded_paper_controller_final_decision.json", final)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def acquire_controller_lock(*, pid: int, pid_path: Path, lock_path: Path) -> dict[str, Any]:
    """Acquire single-instance lock. Refuses if another live controller owns lock/pid."""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    for path, label in ((lock_path, "lock"), (pid_path, "pid")):
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            try:
                other = int(raw)
            except Exception:
                other = None
            if other is not None and other != pid and _pid_alive(other):
                return {
                    "acquired": False,
                    "blocked_by_pid": other,
                    "source": label,
                    "reason": "ACTIVE_CONTROLLER_ALREADY_RUNNING",
                }
            if other is not None and other != pid and not _pid_alive(other):
                # Stale cleanup allowed only when PID does not exist.
                try:
                    path.unlink()
                except Exception:
                    pass
    pid_path.write_text(str(pid) + "\n", encoding="utf-8")
    lock_path.write_text(str(pid) + "\n", encoding="utf-8")
    return {
        "acquired": True,
        "pid": pid,
        "lock_path": str(lock_path),
        "pid_path": str(pid_path),
    }


def release_controller_lock(*, pid: int, pid_path: Path, lock_path: Path) -> None:
    for path in (pid_path, lock_path):
        if not path.exists():
            continue
        try:
            if path.read_text(encoding="utf-8").strip() == str(pid):
                path.unlink()
        except Exception:
            pass


def run_controller(
    *,
    root: Path,
    max_cycles: int,
    interval_seconds: int,
    max_duration_hours: float,
    skip_refresh: bool = False,
    one_cycle: bool = False,
    sleep_fn: SleepFn | None = None,
    background_safe: bool = False,
) -> int:
    research = root / "data" / "research" / "paper_simulator"
    sleep = sleep_fn or time.sleep
    pid = os.getpid()
    pid_path = root / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
    lock_path = root / "run" / "bounded_paper_trading_controller_auto_ledger.lock"
    if background_safe:
        lock = acquire_controller_lock(pid=pid, pid_path=pid_path, lock_path=lock_path)
        if not lock.get("acquired"):
            _log(
                f"controller_start_blocked pid={pid} "
                f"blocked_by={lock.get('blocked_by_pid')} reason={lock.get('reason')}",
                LOG_PATH,
            )
            print(json.dumps({"status": "BLOCKED_ACTIVE_CONTROLLER", **lock}, indent=2))
            return 3
    else:
        # Still write pid for one-cycle/test visibility without exclusive lock refusal
        # when explicitly not background-safe; repair/start path uses background-safe.
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(pid) + "\n", encoding="utf-8")

    stop_flag = {"stop": False}

    def _handle_sig(_signum: int, _frame: Any) -> None:
        stop_flag["stop"] = True
        _log("signal_received_stopping", LOG_PATH)

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    started = time.time()
    last_cycle: dict[str, Any] | None = None
    stop_reason: str | None = None

    write_status_bundle(
        research=research,
        running=True,
        pid=pid,
        cycle_idx=0,
        max_cycles=max_cycles,
        interval_seconds=interval_seconds,
        max_duration_hours=max_duration_hours,
        last_cycle=None,
    )
    _log(
        f"controller_start pid={pid} max_cycles={max_cycles} "
        f"interval_seconds={interval_seconds} max_duration_hours={max_duration_hours} "
        f"lock_protection_enabled={bool(background_safe)}",
        LOG_PATH,
    )

    for cycle_idx in range(1, max_cycles + 1):
        if stop_flag["stop"]:
            stop_reason = "SIGNAL"
            break
        if (time.time() - started) / 3600.0 >= max_duration_hours:
            stop_reason = "MAX_DURATION"
            break
        try:
            last_cycle = run_one_cycle(
                root=root,
                cycle_idx=cycle_idx,
                skip_refresh=skip_refresh,
            )
            _log(
                f"cycle={cycle_idx} status={last_cycle.get('cycle_status')} "
                f"action={last_cycle.get('action_taken')} "
                f"market={last_cycle.get('latest_market_ts')} "
                f"decision={last_cycle.get('latest_decision_log_ts')}",
                LOG_PATH,
            )
            write_status_bundle(
                research=research,
                running=True,
                pid=pid,
                cycle_idx=cycle_idx,
                max_cycles=max_cycles,
                interval_seconds=interval_seconds,
                max_duration_hours=max_duration_hours,
                last_cycle=last_cycle,
            )
            if last_cycle.get("stop_controller"):
                stop_reason = str(last_cycle.get("reason") or last_cycle.get("cycle_status"))
                break
        except Exception as exc:  # noqa: BLE001
            stop_reason = f"ERROR:{exc}"
            _log(f"cycle_error={exc}\n{traceback.format_exc()}", LOG_PATH)
            write_status_bundle(
                research=research,
                running=False,
                pid=pid,
                cycle_idx=cycle_idx,
                max_cycles=max_cycles,
                interval_seconds=interval_seconds,
                max_duration_hours=max_duration_hours,
                last_cycle=last_cycle,
                stop_reason=stop_reason,
            )
            return 1

        if one_cycle:
            stop_reason = "ONE_CYCLE"
            break
        if cycle_idx >= max_cycles:
            stop_reason = "MAX_CYCLES"
            break
        if interval_seconds > 0:
            # Interruptible sleep
            end = time.time() + interval_seconds
            while time.time() < end:
                if stop_flag["stop"]:
                    break
                sleep(min(1.0, end - time.time()))

    status = _load_json(research / "bounded_paper_controller_status.json") or {}
    write_status_bundle(
        research=research,
        running=False,
        pid=pid,
        cycle_idx=int(status.get("cycle_idx") or 0),
        max_cycles=max_cycles,
        interval_seconds=interval_seconds,
        max_duration_hours=max_duration_hours,
        last_cycle=last_cycle,
        stop_reason=stop_reason or "COMPLETED",
    )
    _log(f"controller_stop reason={stop_reason}", LOG_PATH)
    if background_safe:
        release_controller_lock(pid=pid, pid_path=pid_path, lock_path=lock_path)
    elif pid_path.exists():
        try:
            if pid_path.read_text(encoding="utf-8").strip() == str(pid):
                pid_path.unlink()
        except Exception:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--approved-bounded-paper-controller-auto-ledger",
        action="store_true",
        required=False,
    )
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--no-real-execution", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=DEFAULT_MAX_CYCLES)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-duration-hours", type=float, default=DEFAULT_MAX_DURATION_HOURS)
    parser.add_argument("--background-safe", action="store_true")
    parser.add_argument("--one-cycle", action="store_true")
    parser.add_argument("--skip-refresh", action="store_true")
    args = parser.parse_args(argv)

    if not (
        args.approved_bounded_paper_controller_auto_ledger
        and args.paper_only
        and args.no_real_execution
    ):
        print(
            json.dumps(
                {
                    "status": "BLOCKED_APPROVAL_REQUIRED",
                    "required_flags": [
                        "--approved-bounded-paper-controller-auto-ledger",
                        "--paper-only",
                        "--no-real-execution",
                    ],
                    "approval_phrase": APPROVAL_PHRASE,
                },
                indent=2,
            )
        )
        return 2

    return run_controller(
        root=args.root.resolve(),
        max_cycles=max(1, int(args.max_cycles)),
        interval_seconds=max(0, int(args.interval_seconds)),
        max_duration_hours=float(args.max_duration_hours),
        skip_refresh=bool(args.skip_refresh),
        one_cycle=bool(args.one_cycle),
        background_safe=bool(args.background_safe),
    )


if __name__ == "__main__":
    raise SystemExit(main())
