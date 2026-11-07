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
LIVE_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(LIVE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(LIVE_SCRIPTS_DIR))

from paper_trade_economics import (  # type: ignore  # noqa: E402
    ECONOMICS_SOURCE,
    ENTRY_FEE_BPS as PAPER_ENTRY_FEE_BPS,
    EXIT_FEE_BPS as PAPER_EXIT_FEE_BPS,
    INITIAL_CAPITAL_USD,
    MAX_RISK_PER_TRADE_FRACTION,
    MAX_RISK_USD,
    NORMAL_ENTRY_SLIPPAGE_BPS,
    NORMAL_EXIT_SLIPPAGE_BPS,
    POSITION_SIZING_MODE,
    SIZING_METHOD as PAPER_SIZING_METHOD,
    STOP_FORCED_EXIT_SLIPPAGE_BPS,
    STOP_LOSS_BPS as PAPER_STOP_LOSS_BPS,
    TAKE_PROFIT_BPS as PAPER_TAKE_PROFIT_BPS,
    closed_trade_economics as compute_closed_trade_economics,
    execution_quality_status,
    resolve_risk_sizing as resolve_canonical_risk_sizing,
    stop_take_prices as canonical_stop_take_prices,
)

APPROVAL_PHRASE = (
    "APPROVE_BOUNDED_PAPER_TRADING_CONTROLLER_AUTO_LEDGER_NO_REAL_EXECUTION"
)
CONTROLLER_MODE = "PAPER_ONLY"
PAPER_CONTEXT_POLICY_MODE = "TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS"
PAPER_CONTEXT_HOLD_MODE = "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END"

DEFAULT_MAX_CYCLES = 96
DEFAULT_INTERVAL_SECONDS = 900
DEFAULT_MAX_DURATION_HOURS = 24
# Patch 2B.2: paper is a read-only consumer of the decision plane by default.
DEFAULT_SKIP_REFRESH = True
PAPER_OWNERSHIP_CLASS = "PAPER_READ_ONLY_CONSUMER"

STOP_LOSS_BPS = PAPER_STOP_LOSS_BPS
TAKE_PROFIT_BPS = PAPER_TAKE_PROFIT_BPS
ENTRY_FEE_BPS = PAPER_ENTRY_FEE_BPS
EXIT_FEE_BPS = PAPER_EXIT_FEE_BPS
COST_MODEL_BPS = ENTRY_FEE_BPS + EXIT_FEE_BPS + NORMAL_ENTRY_SLIPPAGE_BPS + NORMAL_EXIT_SLIPPAGE_BPS
PAPER_INITIAL_EQUITY = INITIAL_CAPITAL_USD
PAPER_NOTIONAL = 10000.0  # legacy constant; not used for valid-stop paper sizing.
PAPER_MAX_RISK_PCT = MAX_RISK_PER_TRADE_FRACTION
PAPER_MAX_RISK_USD = MAX_RISK_USD
RISK_SIZING_METHOD = PAPER_SIZING_METHOD
POSITION_SIZING_MODE_LABEL = POSITION_SIZING_MODE
ENTRY_BLOCKED_NO_VALID_STOP_FOR_RISK_SIZING = "ENTRY_BLOCKED_NO_VALID_STOP_FOR_RISK_SIZING"
ENTRY_BLOCKED_INVALID_STOP_DISTANCE = "ENTRY_BLOCKED_INVALID_STOP_DISTANCE"
SYNTHETIC_FORBIDDEN_PRICE = 100000.0

# Terminal lifecycle only when context is already non-directional.
# CHALLENGED must NOT force exit while directional context remains.
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
    # Phase-1 origin diagnostics (reference != execution observation).
    "context_reference_price",
    "context_reference_timestamp",
    "context_episode_id",
    "execution_observation_price",
    "distance_from_context_bps",
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
    "market_snapshot_source",
    "market_snapshot_observed_at",
    "market_snapshot_age_seconds",
    "market_snapshot_fallback_used",
    "market_snapshot_warning",
    "market_snapshot_available",
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
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("+00:00"):
            return s.replace("+00:00", "Z")
        if "T" not in s and " " in s:
            return s.replace(" ", "T") + ("Z" if not s.endswith("Z") else "")
        return s
    ts = pd.Timestamp(v)
    if pd.isna(ts):
        return ""
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _metadata_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _metadata_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_metadata_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (datetime, pd.Timestamp)):
        return _ts_iso(value) or None
    return value


def _metadata_json(payload: dict[str, Any]) -> str:
    return json.dumps(_metadata_safe(payload))


def _resolve_action_clock(
    decision: dict[str, Any],
    *,
    controller_cycle_at: str | None = None,
) -> dict[str, Any]:
    """Separate source bucket time from paper action time (prefer intrabar events)."""
    try:
        from paper_action_clock import lookup_intrabar_event_for_source, resolve_paper_action_ts
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paper_action_clock import lookup_intrabar_event_for_source, resolve_paper_action_ts

    source = decision.get("source_context_ts") or decision.get("candle_timestamp") or decision.get(
        "latest_decision_log_ts"
    )
    detected = (
        decision.get("context_event_detected_at")
        or decision.get("event_detected_at")
        or decision.get("detected_at")
    )
    decision_at = (
        decision.get("decision_available_at")
        or decision.get("decision_written_at_utc")
        or decision.get("signal_fields_generated_at_utc")
    )
    intrabar_detected = None
    intrabar_event_id = decision.get("intrabar_event_id")
    provisional = None
    events_path = LIVE / "intrabar_context_events.parquet"
    if events_path.exists():
        try:
            events = pd.read_parquet(events_path)
            ev = lookup_intrabar_event_for_source(
                events,
                source_context_ts=source,
                event_types=("CONTEXT_START", "CONTEXT_END", "CONTEXT_FLIP"),
            )
            if ev:
                intrabar_detected = ev.get("event_detected_at")
                intrabar_event_id = ev.get("event_id")
                provisional = bool(ev.get("provisional"))
                if not detected:
                    detected = intrabar_detected
        except Exception:
            pass
    clock = resolve_paper_action_ts(
        intrabar_event_detected_at=intrabar_detected,
        context_event_detected_at=detected,
        decision_available_at=decision_at,
        controller_cycle_at=controller_cycle_at,
        source_context_ts=source,
        intrabar_event_id=intrabar_event_id,
        intrabar_event_provisional=provisional,
    )
    clock["action_clock_source"] = clock.get("clock_source_used")
    clock["clock_warning"] = (clock.get("warnings") or [None])[0]
    return clock


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
    stop, take = canonical_stop_take_prices(side, entry)
    return float(stop), float(take)


def _sizing_block(reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "allowed": False,
        "reason": reason,
        "sizing_method": RISK_SIZING_METHOD,
        "position_sizing_mode": POSITION_SIZING_MODE_LABEL,
        "initial_equity": PAPER_INITIAL_EQUITY,
        "max_risk_pct": PAPER_MAX_RISK_PCT,
        "max_risk_usd": PAPER_MAX_RISK_USD,
        "fixed_notional_used": False,
    }
    out.update(extra)
    return out


def resolve_entry_risk_sizing(
    *,
    side: str,
    entry_price: Any,
    stop_loss_price: Any = None,
    take_profit_price: Any = None,
    slippage_bps: Any = None,
) -> dict[str, Any]:
    side_u = str(side or "").upper()
    entry = _sf(entry_price)
    take = _sf(take_profit_price)
    if take is None and entry is not None and entry > 0 and side_u in {"LONG", "SHORT"}:
        try:
            _, derived_take = compute_stop_take(side_u, float(entry))
            take = _sf(derived_take)
        except Exception:
            take = None
    sizing = resolve_canonical_risk_sizing(
        side=side_u,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take,
        block_missing_stop_reason=ENTRY_BLOCKED_NO_VALID_STOP_FOR_RISK_SIZING,
        block_invalid_stop_reason=ENTRY_BLOCKED_INVALID_STOP_DISTANCE,
    ).to_controller_dict()
    return sizing


def sizing_metadata(sizing: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "sizing_method",
        "position_sizing_mode",
        "initial_equity",
        "max_risk_pct",
        "max_risk_usd",
        "stop_loss_price",
        "take_profit_price",
        "stop_loss_source",
        "take_profit_source",
        "stop_distance",
        "effective_loss_per_unit_at_stop",
        "estimated_loss_at_stop",
        "entry_fee_usd",
        "estimated_exit_fee_usd_at_stop",
        "estimated_slippage_usd_at_stop",
        "entry_slippage_usd",
        "estimated_exit_slippage_usd_at_stop",
        "fee_model_used",
        "entry_fee_bps",
        "exit_fee_bps",
        "entry_slippage_bps",
        "exit_slippage_bps",
        "slippage_bps",
        "fixed_notional_used",
        "quantity_btc",
        "notional_usd",
        "position_size_btc",
        "position_notional_usd",
        "risk_amount_usd",
        "stop_distance_usd",
        "max_risk_per_trade_pct",
        "initial_capital_usd",
        "economics_source",
    )
    return {k: sizing.get(k) for k in keys}


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
    hold_mode: str | None = None,
) -> dict[str, Any]:
    side_u = str(side).upper()
    ctx = str(latest_context or "")
    life = str(latest_lifecycle_state or "").upper()
    hold_until = str(hold_mode or PAPER_CONTEXT_HOLD_MODE).upper() == "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END"

    if side_u == "LONG":
        unrealized_pnl_bps = ((current_price - entry_price) / entry_price) * 10000.0
        unrealized_pnl_usd = quantity * (current_price - entry_price)
        stop_loss_hit = latest_low <= stop_loss_price
        take_profit_hit = latest_high >= take_profit_price
        # Hold while LONG_CONTEXT remains (including CHALLENGED/WEAK/QUESTIONABLE).
        context_exit = ctx != "LONG_CONTEXT"
        if ctx == "LONG_CONTEXT" and life in CONTEXT_EXIT_LIFECYCLES:
            # Explicit terminal lifecycle with non-matching should already be non-LONG;
            # if still LONG_CONTEXT, do not exit on CHALLENGED-like labels.
            context_exit = False
        hold_action = "PREVIEW_HOLD_LONG"
        stop_action = "PREVIEW_CLOSE_LONG_STOP_LOSS"
        take_action = "PREVIEW_CLOSE_LONG_TAKE_PROFIT"
        ctx_action = "PREVIEW_CLOSE_LONG_CONTEXT_EXIT"
    elif side_u == "SHORT":
        unrealized_pnl_bps = ((entry_price - current_price) / entry_price) * 10000.0
        unrealized_pnl_usd = quantity * (entry_price - current_price)
        stop_loss_hit = latest_high >= stop_loss_price
        take_profit_hit = latest_low <= take_profit_price
        context_exit = ctx != "SHORT_CONTEXT"
        if ctx == "SHORT_CONTEXT" and life in CONTEXT_EXIT_LIFECYCLES:
            context_exit = False
        hold_action = "PREVIEW_HOLD_SHORT"
        stop_action = "PREVIEW_CLOSE_SHORT_STOP_LOSS"
        take_action = "PREVIEW_CLOSE_SHORT_TAKE_PROFIT"
        ctx_action = "PREVIEW_CLOSE_SHORT_CONTEXT_EXIT"
    else:
        raise ValueError(f"unsupported_side:{side}")

    same_bar = bool(stop_loss_hit and take_profit_hit)
    if hold_until:
        # Research hold: exit only on directional context end / flip / observe.
        if context_exit:
            if ctx == "SHORT_CONTEXT" and side_u == "LONG":
                end_code = "CONTEXT_FLIP_LONG_TO_SHORT"
            elif ctx == "LONG_CONTEXT" and side_u == "SHORT":
                end_code = "CONTEXT_FLIP_SHORT_TO_LONG"
            elif ctx in {"OBSERVE", "NO_ACTIVE_CONTEXT", "STAND_ASIDE", "INVALIDATED", ""}:
                end_code = "CONTEXT_END_EVENT_LONG" if side_u == "LONG" else "CONTEXT_END_EVENT_SHORT"
            else:
                end_code = "CONTEXT_END_EVENT_LONG" if side_u == "LONG" else "CONTEXT_END_EVENT_SHORT"
            action, reason = (
                ctx_action,
                f"{end_code}|HOLD_UNTIL_DIRECTIONAL_CONTEXT_END:{ctx}/{life or 'UNKNOWN'}",
            )
        else:
            action, reason = hold_action, "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END"
    elif same_bar:
        action, reason = stop_action, "SAME_BAR_STOP_AND_TAKE_CONSERVATIVE_STOP_FIRST"
    elif stop_loss_hit:
        action, reason = stop_action, "STOP_LOSS_HIT"
    elif take_profit_hit:
        action, reason = take_action, "TAKE_PROFIT_HIT"
    elif context_exit:
        end_code = "CONTEXT_END_EVENT_LONG" if side_u == "LONG" else "CONTEXT_END_EVENT_SHORT"
        action, reason = (
            ctx_action,
            f"{end_code}|CONTEXT_OR_LIFECYCLE_EXIT:{ctx}/{life or 'UNKNOWN'}",
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
        "paper_context_hold_mode": hold_mode or PAPER_CONTEXT_HOLD_MODE,
        "exited_on_flip": "FLIP" in str(reason),
        "exited_on_observe": ctx in {"OBSERVE", "NO_ACTIVE_CONTEXT"},
        "exited_on_invalidated": life == "INVALIDATED" and context_exit,
        "exited_on_true_context_end": bool(context_exit),
    }


def _truthy_decision_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


def _normalized_decision_side(decision: dict[str, Any]) -> str | None:
    for key in ("intended_side", "trade_side", "side"):
        side = str(decision.get(key) or "").strip().upper()
        if side in {"LONG", "SHORT"}:
            return side
    return None


def _directional_open_action_side(decision: dict[str, Any]) -> str | None:
    for key in ("paper_action_candidate", "paper_policy_action", "paper_action", "policy_action"):
        action = str(decision.get(key) or "").strip().upper()
        if "OPEN_LONG" in action:
            return "LONG"
        if "OPEN_SHORT" in action:
            return "SHORT"
    return None


def _paper_context_quality(lifecycle_state: Any) -> str:
    life = str(lifecycle_state or "").strip().upper()
    if life == "CANDIDATE":
        return "CANDIDATE"
    if life == "CHALLENGED":
        return "CHALLENGED"
    if life in {"ACTIVE", "CONFIRMED"}:
        return "CONFIRMED"
    return life or "UNKNOWN"


def _paper_collection_entry_allowed(ctx: Any, lifecycle_state: Any) -> bool:
    context = str(ctx or "").strip().upper()
    return context in {"LONG_CONTEXT", "SHORT_CONTEXT"} and _paper_context_quality(lifecycle_state) in {
        "CANDIDATE",
        "CHALLENGED",
        "CONFIRMED",
    }


def _explicit_decision_context_start_event(decision: dict[str, Any]) -> dict[str, Any]:
    if not _truthy_decision_flag(decision.get("context_start_event")):
        return {"usable": False}
    lifecycle_state = str(decision.get("lifecycle_state") or "").strip().upper()
    candidate_context = str(decision.get("candidate_context") or "").strip().upper()
    if lifecycle_state != "CANDIDATE" or candidate_context not in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        return {"usable": False}
    intended_side = _normalized_decision_side(decision)
    action_side = _directional_open_action_side(decision)
    expected_context = "LONG_CONTEXT" if intended_side == "LONG" else "SHORT_CONTEXT" if intended_side == "SHORT" else None
    if intended_side is None or action_side is None or intended_side != action_side:
        return {"usable": False}
    if candidate_context != expected_context:
        return {"usable": False}
    return {
        "usable": True,
        "context_start_event": True,
        "context_start_event_source": str(
            decision.get("context_start_event_source") or "decision_row.context_start_event"
        ),
        "fresh": True,
    }


def evaluate_flat_entry_gate(
    decision: dict[str, Any],
    *,
    previous_decision: dict[str, Any] | None = None,
    traded_episode_memory: dict[str, Any] | None = None,
    position_already_open: bool = False,
) -> dict[str, Any]:
    """Entry gate for paper collection with duplicate/exposure safety."""
    # Local import keeps controller boot resilient if engine path shifts in tests.
    try:
        from paper_policy_engine import (
            ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED,
            ENTRY_BLOCKED_CONTEXT_STALE,
            ENTRY_BLOCKED_NO_CONTEXT_START_EVENT,
            ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT,
            ENTRY_BLOCKED_POSITION_ALREADY_OPEN,
            ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY,
            derive_context_episode_key,
            derive_context_start_event,
            is_context_episode_already_traded,
            is_fresh_context_start,
            is_directional_context,
            is_missing_context_episode_key,
            normalize_effective_context,
        )
    except Exception:  # pragma: no cover
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paper_policy_engine import (
            ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED,
            ENTRY_BLOCKED_CONTEXT_STALE,
            ENTRY_BLOCKED_NO_CONTEXT_START_EVENT,
            ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT,
            ENTRY_BLOCKED_POSITION_ALREADY_OPEN,
            ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY,
            derive_context_episode_key,
            derive_context_start_event,
            is_context_episode_already_traded,
            is_fresh_context_start,
            is_directional_context,
            is_missing_context_episode_key,
            normalize_effective_context,
        )

    active_context_raw = str(decision.get("active_market_context") or "").strip().upper()
    # stale_flag includes pipeline_pending after reclassify; decision_stale is data-stale only.
    stale = bool(
        decision.get("decision_stale")
        or decision.get("pipeline_pending")
        or decision.get("stale_flag")
    )
    ctx = normalize_effective_context(decision)
    prev = normalize_effective_context(previous_decision) if previous_decision else normalize_effective_context(
        decision.get("previous_active_market_context")
    )
    if prev is None and previous_decision is None:
        prev = "NONE"
    # Prefer candidate / lifecycle episode start layer for research entry timing / freshness.
    start_row = dict(decision)
    if previous_decision:
        start_row.setdefault("previous_active_market_context", previous_decision.get("active_market_context"))
    explicit_start = _explicit_decision_context_start_event(decision)
    if explicit_start.get("usable"):
        explicit_prev = normalize_effective_context(decision.get("previous_active_market_context"))
        if explicit_prev is not None:
            prev = explicit_prev
        derived = {
            "context_start_event": True,
            "context_start_event_source": explicit_start.get("context_start_event_source"),
            "fresh": True,
        }
    else:
        derived = derive_context_start_event(prev, decision, start_row)
    start_row["context_start_event"] = bool(derived.get("context_start_event"))
    start_row["context_start_event_source"] = derived.get("context_start_event_source")
    episode_key = derive_context_episode_key(decision)
    reasons: list[str] = []

    life = str(decision.get("lifecycle_state") or "")
    context_quality = _paper_context_quality(life)
    collection_allowed = _paper_collection_entry_allowed(ctx, life) and active_context_raw != "STAND_ASIDE"
    fresh = bool(derived.get("fresh")) or is_fresh_context_start(prev, ctx, start_row)
    original_gate_reason = ENTRY_BLOCKED_NO_CONTEXT_START_EVENT if not fresh else None

    if position_already_open:
        reasons.append(ENTRY_BLOCKED_POSITION_ALREADY_OPEN)
    if stale:
        reasons.append(ENTRY_BLOCKED_CONTEXT_STALE)
    if active_context_raw == "STAND_ASIDE" or not is_directional_context(ctx):
        reasons.append(ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT)
    if not fresh and not collection_allowed:
        reasons.append(ENTRY_BLOCKED_NO_CONTEXT_START_EVENT)
    if is_missing_context_episode_key(episode_key):
        reasons.append(ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY)
    if is_context_episode_already_traded(traded_episode_memory, episode_key):
        reasons.append(ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED)

    # Secondary metadata only (TRADE_ALL: never hard-block on quality/confidence/edge).
    edge = _sf(decision.get("expected_edge_bps"))
    conf = _sf(decision.get("confidence"))
    quality = str(decision.get("context_quality_label") or decision.get("raw_context_status") or "")
    secondary: list[str] = []
    if life.upper() not in {"ACTIVE", "CHALLENGED", "CANDIDATE", ""}:
        secondary.append(f"lifecycle_note:{life}")
    if edge is None or edge <= 0:
        secondary.append("expected_edge_bps_not_positive")
    if conf is None:
        secondary.append("confidence_missing")
    if quality:
        secondary.append(f"quality_label:{quality}")

    ok = not reasons
    side = "LONG" if ctx == "LONG_CONTEXT" else ("SHORT" if ctx == "SHORT_CONTEXT" else None)
    try:
        from paper_policy_engine import resolve_research_context_start
    except Exception:
        resolve_research_context_start = None  # type: ignore
    start_meta = resolve_research_context_start(start_row) if resolve_research_context_start else {}
    return {
        "allowed": ok,
        "block_reasons": reasons,
        "secondary_notes": secondary,
        "side": side if ok else None,
        "policy_action": f"OPEN_{side}" if ok and side else "NO_TRADE",
        "paper_action": f"INTENT_OPEN_{side}" if ok and side else "NO_SIGNAL",
        "context_start_event": bool(fresh),
        "context_start_event_source": derived.get("context_start_event_source"),
        "directional_flip_detected": bool(
            prev in {"LONG_CONTEXT", "SHORT_CONTEXT"} and ctx in {"LONG_CONTEXT", "SHORT_CONTEXT"} and prev != ctx
        ),
        "paper_collection_trade": bool(ok and collection_allowed),
        "context_quality": context_quality,
        "doubt_flag": bool(ok and context_quality in {"CANDIDATE", "CHALLENGED"}),
        "active_market_context": decision.get("active_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "raw_market_context": decision.get("raw_market_context"),
        "challenge_context": decision.get("challenge_context"),
        "candidate_context": decision.get("candidate_context"),
        "original_gate_reason": original_gate_reason if ok and collection_allowed else None,
        "paper_entry_basis": "ACTIVE_DIRECTIONAL_CONTEXT" if ok and collection_allowed else None,
        "previous_context": prev,
        "current_context": ctx,
        "context_episode_key": episode_key,
        "lifecycle_episode_id": decision.get("lifecycle_episode_id"),
        "paper_policy_mode": PAPER_CONTEXT_POLICY_MODE,
        "context_hold_mode": PAPER_CONTEXT_HOLD_MODE,
        "entry_used_context_layer": start_meta.get("entry_used_context_layer"),
        "context_candidate_started_at": start_meta.get("context_candidate_started_at"),
        "context_active_started_at": start_meta.get("context_active_started_at"),
        "context_confirmed_at": start_meta.get("context_confirmed_at"),
        "context_raw_started_at": start_meta.get("context_raw_started_at"),
        "execution_enabled": False,
        "paper_only": True,
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
                "entry_slippage_usd": float(meta.get("entry_slippage_usd") or d.get("slippage_paid") or 0.0),
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


def _reclassify_decision_freshness(row: dict[str, Any], *, live: Path) -> dict[str, Any]:
    """Recompute decision freshness against current live/lifecycle data timestamps."""
    try:
        logger_mod = _load_module(
            "append_context_decision_log_freshness",
            ROOT / "scripts" / "live" / "append_context_decision_log.py",
        )
    except Exception:
        return row
    try:
        feed = pd.read_parquet(live / "live_market_feed.parquet")
        live_ts = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce").max()
    except Exception:
        live_ts = None
    life_ts = None
    life_path = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    try:
        if life_path.exists():
            life = pd.read_parquet(life_path, columns=["timestamp"])
            life_ts = pd.to_datetime(life["timestamp"], utc=True, errors="coerce").max()
    except Exception:
        life_ts = None
    decision_ts = row.get("candle_timestamp") or row.get("latest_decision_log_ts")
    freshness = logger_mod.classify_decision_freshness(
        decision_market_ts=decision_ts,
        lifecycle_ts=life_ts,
        live_ts=live_ts,
    )
    out = dict(row)
    out["decision_stale"] = bool(freshness.get("decision_stale"))
    out["pipeline_pending"] = bool(freshness.get("pipeline_pending"))
    out["technical_refresh_lag_present"] = bool(freshness.get("technical_refresh_lag_present"))
    out["decision_freshness_status"] = freshness.get("decision_freshness_status")
    out["decision_stale_reason"] = freshness.get("decision_stale_reason")
    # Entry gate: block on true stale OR unfinished pipeline; do not treat live-ahead alone as data-stale.
    out["stale_flag"] = bool(freshness.get("decision_stale") or freshness.get("pipeline_pending"))
    return out


def load_latest_decision(live: Path) -> dict[str, Any]:
    log = pd.read_parquet(live / "context_decision_log.parquet")
    if log.empty:
        return {}
    tmp = log.copy()
    tmp["_ts"] = pd.to_datetime(tmp["candle_timestamp"], utc=True, errors="coerce")
    tmp = tmp.sort_values("_ts")
    row = tmp.iloc[-1].to_dict()
    row["latest_decision_log_ts"] = _ts_iso(row.get("candle_timestamp"))
    # Enrich with lifecycle candidate start layer (research timing; no cognition mutation).
    life_path = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    if life_path.exists():
        try:
            life = pd.read_parquet(life_path)
            if not life.empty and "timestamp" in life.columns:
                life = life.copy()
                life["_ts"] = pd.to_datetime(life["timestamp"], utc=True, errors="coerce")
                hit = life[life["_ts"] == tmp.iloc[-1]["_ts"]]
                if hit.empty:
                    hit = life.sort_values("_ts").tail(1)
                if len(hit):
                    lr = hit.iloc[-1]
                    for k in (
                        "candidate_started_at",
                        "candidate_context",
                        "candidate_reason",
                        "active_context_started_at",
                        "raw_market_context",
                        "raw_context_status",
                        "lifecycle_state",
                        "previous_active_market_context",
                        "lifecycle_episode_id",
                        "lifecycle_episode_start_time",
                        "lifecycle_episode_end_time",
                        "transition_reason",
                        "context_start_event",
                        "context_start_event_source",
                        "directional_flip_detected",
                        "context_end_event",
                        "context_origin_price",
                        "context_entered_at",
                        "context_episode_id",
                        "context_direction",
                        "context_distance_bps",
                        "context_favorable_distance_bps",
                        "context_adverse_distance_bps",
                    ):
                        if k in lr.index and (
                            row.get(k) is None
                            or (isinstance(row.get(k), float) and pd.isna(row.get(k)))
                            or (k == "context_start_event" and row.get(k) is None)
                        ):
                            row[k] = lr.get(k)
                    if "context_quality_label" not in row or row.get("context_quality_label") is None:
                        row["context_quality_label"] = lr.get("raw_context_status")
        except Exception:
            pass
    return _reclassify_decision_freshness(row, live=live)


def load_previous_decision(live: Path, *, before_ts: Any = None) -> dict[str, Any]:
    """Return the decision row immediately before the latest (or before_ts)."""
    path = live / "context_decision_log.parquet"
    if not path.exists():
        return {}
    log = pd.read_parquet(path)
    if log.empty or len(log) < 2:
        return {}
    tmp = log.copy()
    tmp["_ts"] = pd.to_datetime(tmp["candle_timestamp"], utc=True, errors="coerce")
    tmp = tmp.dropna(subset=["_ts"]).sort_values("_ts")
    if before_ts is not None:
        cut = pd.to_datetime(before_ts, utc=True, errors="coerce")
        tmp = tmp[tmp["_ts"] < cut]
    else:
        tmp = tmp.iloc[:-1]
    if tmp.empty:
        return {}
    return tmp.iloc[-1].to_dict()


def traded_episode_memory_path(research: Path) -> Path:
    return research / "paper_traded_context_episodes.json"


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


def _import_market_snapshot_provider():
    try:
        from market_data_snapshot_provider import (
            MARKET_DATA_SNAPSHOT_UNAVAILABLE,
            get_fresh_market_snapshot,
        )
    except Exception:  # pragma: no cover
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from market_data_snapshot_provider import (
            MARKET_DATA_SNAPSHOT_UNAVAILABLE,
            get_fresh_market_snapshot,
        )
    return get_fresh_market_snapshot, MARKET_DATA_SNAPSHOT_UNAVAILABLE


def fetch_cycle_market_snapshot(*, max_age_seconds: float = 90.0) -> dict[str, Any]:
    """Fresh snapshot for ENTRY/EXIT fills. Never invent prices."""
    get_fresh_market_snapshot, unavailable = _import_market_snapshot_provider()
    snap = get_fresh_market_snapshot(symbol="BTCUSDT", max_age_seconds=max_age_seconds)
    if not isinstance(snap, dict):
        return {
            "available": False,
            "reason": unavailable,
            "error": unavailable,
            "source": None,
            "price": None,
            "fallback_used": False,
            "warning": None,
            "observed_at_utc": None,
            "source_age_seconds": None,
        }
    return snap


def market_snapshot_fields(snap: dict[str, Any] | None) -> dict[str, Any]:
    snap = snap or {}
    return {
        "market_snapshot_source": snap.get("source"),
        "market_snapshot_observed_at": snap.get("observed_at_utc"),
        "market_snapshot_age_seconds": snap.get("source_age_seconds"),
        "market_snapshot_fallback_used": bool(snap.get("fallback_used")),
        "market_snapshot_warning": snap.get("warning"),
        "market_snapshot_available": bool(snap.get("available")),
    }


def _first_ts_value(*values: Any) -> str | None:
    for value in values:
        ts = _ts_iso(value)
        if ts:
            return ts
    return None


def extract_context_price_diagnostics(
    decision: dict[str, Any],
    *,
    execution_observation_price: float | None = None,
) -> dict[str, Any]:
    """Phase-1 diagnostics: context reference vs execution observation.

    Never treats context_origin_price as a synthetic fill price.
    """
    ref = _sf(
        decision.get("context_origin_price")
        or decision.get("context_reference_price")
    )
    ref_ts = _first_ts_value(
        decision.get("context_entered_at"),
        decision.get("context_reference_timestamp"),
        decision.get("active_context_started_at"),
    )
    episode_id = decision.get("context_episode_id")
    if episode_id is None:
        episode_id = decision.get("lifecycle_episode_id")
    try:
        episode_id_out = int(episode_id) if episode_id is not None and not pd.isna(episode_id) else None
    except (TypeError, ValueError):
        episode_id_out = None
    exec_px = _sf(execution_observation_price)
    dist = None
    direction = str(
        decision.get("context_direction")
        or decision.get("active_market_context")
        or ""
    ).strip().upper()
    if ref is not None and ref > 0 and exec_px is not None:
        if direction == "LONG_CONTEXT" or direction == "LONG":
            dist = round((exec_px - ref) / ref * 10000.0, 6)
        elif direction == "SHORT_CONTEXT" or direction == "SHORT":
            dist = round((ref - exec_px) / ref * 10000.0, 6)
        else:
            dist = _sf(decision.get("context_distance_bps"))
    elif decision.get("context_distance_bps") is not None:
        dist = _sf(decision.get("context_distance_bps"))
    return {
        "context_reference_price": ref,
        "context_reference_timestamp": ref_ts,
        "context_episode_id": episode_id_out,
        "execution_observation_price": exec_px,
        "distance_from_context_bps": dist,
    }


def resolve_entry_execution_observation(
    decision: dict[str, Any],
    snap: dict[str, Any] | None,
) -> dict[str, Any]:
    # Intentionally does NOT use context_origin_price / context_reference_price as fill.
    event_price = _sf(
        decision.get("event_price")
        or decision.get("context_event_price")
        or decision.get("intrabar_event_price")
        # context_start_event_price kept for true event fills only; origin is separate.
        or decision.get("context_start_event_price")
    )
    event_ts = _first_ts_value(
        decision.get("intrabar_event_detected_at"),
        decision.get("context_event_detected_at"),
        decision.get("event_detected_at"),
        decision.get("context_start_event_ts"),
        decision.get("context_start_event_timestamp"),
    )
    if event_price is not None and event_price > 0 and event_ts:
        return {
            "available": True,
            "price": float(event_price),
            "execution_ts": event_ts,
            "source": "event_price",
            "entry_execution_source": "event_price",
        }

    snap = snap or {}
    snap_price = _sf(snap.get("price"))
    snap_ts = _first_ts_value(snap.get("observed_at_utc"))
    if bool(snap.get("available")) and snap_price is not None and snap_price > 0 and snap_ts:
        entry_src = "ON_DEMAND_PUBLIC_MARKET_DATA" if snap.get("fallback_used") else "INTRABAR_FEED_SNAPSHOT"
        if snap.get("source"):
            entry_src = str(snap["source"])
        return {
            "available": True,
            "price": float(snap_price),
            "execution_ts": snap_ts,
            "source": entry_src,
            "entry_execution_source": entry_src,
        }

    return {
        "available": False,
        "reason": "ENTRY_BLOCKED_NO_ATOMIC_EXECUTION_PRICE",
        "price": None,
        "execution_ts": None,
        "source": None,
        "entry_execution_source": None,
    }


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
    # Patch 1: metadata sidecar only (no ledger semantic change). Requires process restart to activate.
    try:
        rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
        if rel in {
            "data/research/paper_simulator/paper_signals.parquet",
            "data/research/paper_simulator/paper_orders.parquet",
            "data/research/paper_simulator/paper_trades.parquet",
        }:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from runtime_dataset_metadata import emit_metadata_for_path

            emit_metadata_for_path(rel, root=ROOT, metadata_origin="LIVE_WRITER")
    except Exception:
        pass


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
    controller_cycle_at: str | None = None,
    market_snapshot: dict[str, Any] | None = None,
    policy_tags: dict[str, Any] | None = None,
    entry_execution_ts: str | None = None,
    sizing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if abs(entry_price - SYNTHETIC_FORBIDDEN_PRICE) < 1e-9:
        raise RuntimeError("synthetic_price_forbidden")
    sizing_info = dict(
        sizing
        or resolve_entry_risk_sizing(
            side=side,
            entry_price=entry_price,
            stop_loss_price=decision.get("stop_loss_price"),
            take_profit_price=decision.get("take_profit_price"),
        )
    )
    if not sizing_info.get("allowed"):
        raise RuntimeError(str(sizing_info.get("reason") or "risk_sizing_unavailable"))
    stop = float(sizing_info["stop_loss_price"])
    take = float(sizing_info["take_profit_price"]) if sizing_info.get("take_profit_price") is not None else None
    qty = float(sizing_info["quantity_btc"])
    notional = float(sizing_info["notional_usd"])
    fee = float(sizing_info["entry_fee_usd"])
    entry_slippage = float(sizing_info.get("entry_slippage_usd") or 0.0)
    size_meta = sizing_metadata(sizing_info)
    now = _iso_now()
    clock = _resolve_action_clock(decision, controller_cycle_at=controller_cycle_at or now)
    decision_ts = _ts_iso(clock.get("source_context_ts") or decision.get("candle_timestamp") or decision.get("latest_decision_log_ts"))
    source_ts = decision_ts
    policy_action_ts = _ts_iso(clock.get("paper_action_ts") or now)
    paper_action_ts = _ts_iso(entry_execution_ts) or policy_action_ts
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

    snap_fields = market_snapshot_fields(market_snapshot)
    tags = dict(policy_tags or {})
    quality = str(
        tags.get("context_quality_label")
        or decision.get("context_quality_label")
        or decision.get("raw_context_status")
        or ""
    ).upper()
    conf_label = str(tags.get("context_confidence_label") or decision.get("context_confidence_label") or "")
    life_entry = str(decision.get("lifecycle_state") or "")
    clock_meta = {
        "source_context_ts": source_ts,
        "context_event_detected_at": clock.get("context_event_detected_at"),
        "decision_available_at": clock.get("decision_available_at"),
        "controller_cycle_at": clock.get("controller_cycle_at") or now,
        "paper_action_ts": paper_action_ts,
        "policy_action_ts": policy_action_ts,
        "entry_execution_ts": paper_action_ts,
        "entry_execution_source": entry_price_source,
        "action_clock_source": clock.get("action_clock_source") or clock.get("clock_source_used"),
        "clock_source_used": clock.get("clock_source_used"),
        "intrabar_event_id": clock.get("intrabar_event_id"),
        "event_detected_at": clock.get("intrabar_event_detected_at") or clock.get("context_event_detected_at"),
        "clock_warning": clock.get("clock_warning"),
        "clock_warnings": clock.get("warnings") or [],
        "m15_bar_open_ts": clock.get("m15_bar_open_ts"),
        "m15_bar_close_ts": clock.get("m15_bar_close_ts"),
        "paper_policy_mode": tags.get("paper_policy_mode") or PAPER_CONTEXT_POLICY_MODE,
        "context_hold_mode": tags.get("context_hold_mode") or PAPER_CONTEXT_HOLD_MODE,
        "context_quality_label": quality or None,
        "context_confidence_label": conf_label or None,
        "lifecycle_state_at_entry": life_entry,
        "context_candidate_started_at": tags.get("context_candidate_started_at") or decision.get("candidate_started_at"),
        "context_active_started_at": tags.get("context_active_started_at") or decision.get("active_context_started_at"),
        "context_confirmed_at": tags.get("context_confirmed_at") or decision.get("active_context_started_at"),
        "context_raw_started_at": tags.get("context_raw_started_at"),
        "entry_used_context_layer": tags.get("entry_used_context_layer"),
        "was_confirmed_context": quality in {"CONFIRMED", "ACTIVE", ""} or life_entry.upper() == "ACTIVE",
        "was_questionable_context": "QUESTION" in quality,
        "was_challenged_context": life_entry.upper() == "CHALLENGED" or "CHALLENGE" in quality,
        "was_weak_context": "WEAK" in quality,
        "policy_alignment_backfill": False,
        **snap_fields,
    }
    context_quality = str(tags.get("context_quality") or "").strip().upper()
    if not context_quality:
        context_quality = _paper_context_quality(life_entry)
    paper_collection_trade = bool(tags.get("paper_collection_trade")) if "paper_collection_trade" in tags else True
    doubt_flag = bool(tags.get("doubt_flag")) if "doubt_flag" in tags else context_quality in {"CANDIDATE", "CHALLENGED"}
    collection_meta = {
        "paper_collection_trade": paper_collection_trade,
        "context_quality": context_quality,
        "doubt_flag": doubt_flag,
        "active_market_context": decision.get("active_market_context"),
        "lifecycle_state": decision.get("lifecycle_state"),
        "raw_market_context": decision.get("raw_market_context"),
        "challenge_context": decision.get("challenge_context"),
        "candidate_context": decision.get("candidate_context"),
        "context_start_event": bool(tags.get("context_start_event")),
        "context_start_event_source": tags.get("context_start_event_source"),
        "original_gate_reason": tags.get("original_gate_reason"),
        "paper_entry_basis": tags.get("paper_entry_basis") or "ACTIVE_DIRECTIONAL_CONTEXT",
    }
    clock_meta.update(collection_meta)

    origin_diag = extract_context_price_diagnostics(
        decision, execution_observation_price=entry_price
    )
    signal = {
        "signal_id": signal_id,
        "signal_status": "CONTROLLER_AUTO",
        "signal_source": "BOUNDED_PAPER_CONTROLLER",
        "decision_log_ts": decision_ts,
        "source_context_ts": source_ts,
        "paper_action_ts": paper_action_ts,
        "context_event_detected_at": clock_meta["context_event_detected_at"],
        "decision_available_at": clock_meta["decision_available_at"],
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
        "context_reference_price": origin_diag.get("context_reference_price"),
        "context_reference_timestamp": origin_diag.get("context_reference_timestamp"),
        "context_episode_id": origin_diag.get("context_episode_id"),
        "execution_observation_price": origin_diag.get("execution_observation_price"),
        "distance_from_context_bps": origin_diag.get("distance_from_context_bps"),
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
        "notional": notional,
        "status": "FILLED",
        "fill_price": entry_price,
        "filled_quantity": qty,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "paper_only": True,
        "execution_enabled": False,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "metadata_json": _metadata_json(
            {
                "parent_signal_id": signal_id,
                "side": side,
                "order_side": order_side,
                "position_effect": position_effect,
                "intended_entry_price": entry_price,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "entry_price_source": entry_price_source,
                "entry_execution_source": entry_price_source,
                "entry_execution_ts": paper_action_ts,
                "entry_slippage_usd": entry_slippage,
                "fees_usd": fee,
                "slippage_usd": entry_slippage,
                "execution_quality_status": execution_quality_status(execution_source=entry_price_source),
                "market_ts": market_ts,
                **collection_meta,
                **size_meta,
                "approval_phrase": APPROVAL_PHRASE,
            }
        ),
    }
    trade = {
        "paper_trade_id": trade_id,
        "paper_order_id": order_id,
        "position_id": position_id,
        "timestamp": paper_action_ts,
        "symbol": "BTCUSDT",
        "side": order_side,
        "quantity": qty,
        "price": entry_price,
        "notional": notional,
        "fee": fee,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage": entry_slippage,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "realized_pnl": 0.0,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": _metadata_json(
            {
                "trade_type": "ENTRY",
                "parent_signal_id": signal_id,
                "side": side,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "approval_phrase": APPROVAL_PHRASE,
                **size_meta,
                **clock_meta,
            }
        ),
    }
    position = {
        "position_id": position_id,
        "opened_at": paper_action_ts,
        "closed_at": None,
        "symbol": "BTCUSDT",
        "direction": side,
        "quantity": qty,
        "entry_price": entry_price,
        "exit_price": None,
        "notional": notional,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": fee,
        "slippage_paid": entry_slippage,
        "status": "OPEN",
        "opening_decision_id": signal_id,
        "closing_decision_id": None,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": _metadata_json(
            {
                "paper_position_id": position_id,
                "parent_trade_id": trade_id,
                "parent_order_id": order_id,
                "parent_signal_id": signal_id,
                "position_status": "OPEN",
                "side": side,
                "quantity_btc": qty,
                "notional_usd": notional,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "stop_loss_bps": STOP_LOSS_BPS,
                "take_profit_bps": TAKE_PROFIT_BPS,
                "entry_fee_usd": fee,
                "entry_slippage_usd": entry_slippage,
                "fees_usd": fee,
                "slippage_usd": entry_slippage,
                "entry_price_source": entry_price_source,
                "approval_phrase": APPROVAL_PHRASE,
                **size_meta,
                **clock_meta,
            }
        ),
    }
    equity_after = PAPER_INITIAL_EQUITY - fee - entry_slippage
    # Prefer last equity cash if present
    eq_path = research / "paper_equity_curve.parquet"
    if eq_path.exists():
        eq = pd.read_parquet(eq_path)
        if not eq.empty:
            last_eq = float(eq.iloc[-1]["equity"])
            equity_after = last_eq - fee - entry_slippage
    equity = {
        "timestamp": now,
        "cash": equity_after,
        "position_value": notional,
        "equity": equity_after,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": fee,
        "slippage_paid": entry_slippage,
        "drawdown_pct": 0.0,
        "daily_pnl": -(fee + entry_slippage),
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": _metadata_json(
            {
                "paper_equity_snapshot_id": equity_id,
                "equity_snapshot_type": "PAPER_ENTRY_SNAPSHOT",
                "linked_trade_id": trade_id,
                "linked_position_id": position_id,
                **collection_meta,
                **size_meta,
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
        "notional": notional,
        "fee_bps": ENTRY_FEE_BPS,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "execution_enabled": False,
        "paper_only": True,
        "metadata_json": _metadata_json({"approval_phrase": APPROVAL_PHRASE, **collection_meta, **size_meta}),
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
        "entry_ts": paper_action_ts,
        "entry_execution_source": entry_price_source,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "quantity_btc": qty,
        "notional_usd": notional,
        "entry_slippage_usd": entry_slippage,
        "sizing_method": sizing_info.get("sizing_method"),
        "max_risk_usd": sizing_info.get("max_risk_usd"),
        "estimated_loss_at_stop": sizing_info.get("estimated_loss_at_stop"),
        "fixed_notional_used": sizing_info.get("fixed_notional_used"),
        "paper_collection_trade": collection_meta.get("paper_collection_trade"),
        "context_quality": collection_meta.get("context_quality"),
        "doubt_flag": collection_meta.get("doubt_flag"),
        "context_start_event": collection_meta.get("context_start_event"),
        "original_gate_reason": collection_meta.get("original_gate_reason"),
        "paper_entry_basis": collection_meta.get("paper_entry_basis"),
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
    controller_cycle_at: str | None = None,
    market_snapshot: dict[str, Any] | None = None,
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
    open_meta = dict(open_pos.get("meta") or {})
    raw_open = open_pos.get("raw") or {}
    if not open_meta:
        open_meta = _parse_meta(raw_open.get("metadata_json") if isinstance(raw_open, dict) else None)
    entry_fee = _sf(open_meta.get("entry_fee_usd")) or 0.0
    entry_slippage = _sf(open_meta.get("entry_slippage_usd")) or 0.0
    reason = str(exit_preview["exit_preview_reason"])
    action = str(exit_preview["exit_preview_action"])
    exit_source = str((market_snapshot or {}).get("source") or exit_preview.get("exit_execution_source") or "LIVE_CLOSE_OR_STOP_TAKE")
    economics = compute_closed_trade_economics(
        side=side,
        entry_price=entry,
        exit_price=exit_price,
        position_size_btc=qty,
        stop_loss_price=open_pos.get("stop_loss_price"),
        take_profit_price=open_pos.get("take_profit_price"),
        risk_amount_usd=open_meta.get("risk_amount_usd") or open_meta.get("max_risk_usd") or PAPER_MAX_RISK_USD,
        exit_reason=reason,
        exit_execution_source=exit_source,
    )
    exit_fee = float(economics["exit_fee_usd"])
    exit_slippage = float(economics["exit_slippage_usd"])
    net_after_fees_slippage = float(economics["net_pnl_after_fees_slippage"])
    close_cash_delta = realized - exit_fee - exit_slippage
    clock = _resolve_action_clock(decision, controller_cycle_at=controller_cycle_at or now)
    decision_ts = _ts_iso(clock.get("source_context_ts") or decision.get("candle_timestamp") or decision.get("latest_decision_log_ts"))
    paper_action_ts = _ts_iso(clock.get("paper_action_ts") or now)
    snap_fields = market_snapshot_fields(market_snapshot)
    clock_meta = {
        "source_context_ts": decision_ts,
        "context_event_detected_at": clock.get("context_event_detected_at"),
        "decision_available_at": clock.get("decision_available_at"),
        "controller_cycle_at": clock.get("controller_cycle_at") or now,
        "paper_action_ts": paper_action_ts,
        "action_clock_source": clock.get("action_clock_source") or clock.get("clock_source_used"),
        "clock_source_used": clock.get("clock_source_used"),
        "intrabar_event_id": clock.get("intrabar_event_id"),
        "event_detected_at": clock.get("intrabar_event_detected_at") or clock.get("context_event_detected_at"),
        "clock_warning": clock.get("clock_warning"),
        "clock_warnings": clock.get("warnings") or [],
        "m15_bar_open_ts": clock.get("m15_bar_open_ts"),
        "m15_bar_close_ts": clock.get("m15_bar_close_ts"),
        **snap_fields,
    }

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
        "paper_action_ts": paper_action_ts,
        "context_event_detected_at": clock_meta["context_event_detected_at"],
        "decision_available_at": clock_meta["decision_available_at"],
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
        "fee_bps": EXIT_FEE_BPS,
        "slippage_bps": economics["exit_slippage_bps"],
        "paper_only": True,
        "execution_enabled": False,
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "metadata_json": _metadata_json(
            {
                "parent_signal_id": close_signal_id,
                "close_of_position_id": open_pos["position_id"],
                "exit_preview_action": action,
                "exit_reason": reason,
                "approval_phrase": APPROVAL_PHRASE,
                "exit_execution_source": exit_source,
                **economics,
                **clock_meta,
            }
        ),
    }
    trade = {
        "paper_trade_id": close_trade_id,
        "paper_order_id": close_order_id,
        "position_id": open_pos["position_id"],
        "timestamp": paper_action_ts,
        "symbol": open_pos["symbol"],
        "side": order_side,
        "quantity": qty,
        "price": exit_price,
        "notional": notional,
        "fee": exit_fee,
        "fee_bps": EXIT_FEE_BPS,
        "slippage": exit_slippage,
        "slippage_bps": economics["exit_slippage_bps"],
        "realized_pnl": net_after_fees_slippage,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": _metadata_json(
            {
                "trade_type": "EXIT",
                "exit_preview_action": action,
                "exit_reason": reason,
                "approval_phrase": APPROVAL_PHRASE,
                "exit_execution_source": exit_source,
                **economics,
                **clock_meta,
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
            "realized_pnl_usd": net_after_fees_slippage,
            "gross_pnl_before_fees_slippage": economics["gross_pnl_before_fees_slippage"],
            "fees_usd": economics["fees_usd"],
            "slippage_usd": economics["slippage_usd"],
            "net_pnl_after_fees_slippage": net_after_fees_slippage,
            "R": economics["R"],
            "closed_at": paper_action_ts,
            "approval_phrase": APPROVAL_PHRASE,
            **economics,
            **clock_meta,
        }
    )
    pos_df.at[i, "closed_at"] = paper_action_ts
    pos_df.at[i, "exit_price"] = exit_price
    pos_df.at[i, "realized_pnl"] = net_after_fees_slippage
    pos_df.at[i, "unrealized_pnl"] = 0.0
    # Patch 2B.2: force canonical economics totals (not partial increments).
    pos_df.at[i, "fees_paid"] = float(economics["fees_usd"])
    pos_df.at[i, "slippage_paid"] = float(economics["slippage_usd"])
    pos_df.at[i, "status"] = "CLOSED"
    pos_df.at[i, "closing_decision_id"] = close_signal_id
    pos_df.at[i, "execution_enabled"] = False
    pos_df.at[i, "metadata_json"] = _metadata_json(meta)

    last_equity = PAPER_INITIAL_EQUITY
    eq_path = research / "paper_equity_curve.parquet"
    if eq_path.exists():
        eq = pd.read_parquet(eq_path)
        if not eq.empty:
            last_equity = float(eq.iloc[-1]["equity"])
    new_equity = last_equity + close_cash_delta
    equity = {
        "timestamp": now,
        "cash": new_equity,
        "position_value": 0.0,
        "equity": new_equity,
        "realized_pnl": net_after_fees_slippage,
        "unrealized_pnl": 0.0,
        "fees_paid": exit_fee,
        "slippage_paid": exit_slippage,
        "drawdown_pct": 0.0,
        "daily_pnl": close_cash_delta,
        "paper_only": True,
        "execution_enabled": False,
        "metadata_json": _metadata_json(
            {
                "paper_equity_snapshot_id": equity_id,
                "equity_snapshot_type": "PAPER_EXIT_SNAPSHOT",
                "linked_trade_id": close_trade_id,
                "linked_position_id": open_pos["position_id"],
                "exit_preview_action": action,
                "approval_phrase": APPROVAL_PHRASE,
                "equity_cash_delta_usd": close_cash_delta,
                **economics,
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
        "fee_bps": EXIT_FEE_BPS,
        "slippage_bps": economics["exit_slippage_bps"],
        "risk_gate_status": "PASS",
        "risk_block_reason": None,
        "execution_enabled": False,
        "paper_only": True,
        "metadata_json": _metadata_json(
            {"exit_preview_action": action, "approval_phrase": APPROVAL_PHRASE, **economics}
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
        "pnl_usd": net_after_fees_slippage,
        "equity_cash_delta_usd": close_cash_delta,
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
            "decision_built_after_lifecycle_refresh": False,
            "lifecycle_row_reloaded_after_refresh": False,
            "final_context_row_reloaded_after_refresh": False,
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

    # Hard requirement: reload lifecycle/final from disk AFTER refresh, before decision build.
    lifecycle_reloaded = False
    final_reloaded = False
    life_ctx = None
    final_ctx = None
    try:
        life_df = pd.read_parquet(lifecycle)
        lifecycle_reloaded = True
        if not life_df.empty and "timestamp" in life_df.columns:
            life_df = life_df.copy()
            life_df["_ts"] = pd.to_datetime(life_df["timestamp"], utc=True, errors="coerce")
            life_ctx = str(life_df.sort_values("_ts").iloc[-1].get("active_market_context") or "")
    except Exception:
        lifecycle_reloaded = False
    try:
        final_df = pd.read_parquet(final)
        final_reloaded = True
        if not final_df.empty:
            ts_col = "timestamp" if "timestamp" in final_df.columns else None
            if ts_col:
                final_df = final_df.copy()
                final_df["_ts"] = pd.to_datetime(final_df[ts_col], utc=True, errors="coerce")
                last = final_df.sort_values("_ts").iloc[-1]
                final_ctx = str(last.get("market_context") or last.get("active_market_context") or "")
    except Exception:
        final_reloaded = False

    # Pass previous decision so start/flip fields can be derived without relying only on later gate.
    previous_for_row = {}
    try:
        previous_for_row = load_previous_decision(root / "data" / "live")
    except Exception:
        previous_for_row = {}

    row, _preview, _enrich = single_mod.build_decision_preview(
        logger_mod=logger_mod,
        live_feed=live_feed,
        auction_path=auction,
        cognitive_path=cognitive,
        final_path=final,
        lifecycle_path=lifecycle,
        runtime_log=runtime_log,
        corrected_lookup=corrected_lookup,
        previous_decision=previous_for_row or None,
    )
    # Force paper/execution safety on decision row
    row["execution_enabled"] = False
    row["paper_signal_write_allowed"] = False
    row["paper_loop_allowed"] = False

    decision_ctx = str(row.get("active_market_context") or "")
    mismatch_reason = None
    matches = True
    if life_ctx and decision_ctx and life_ctx.upper() != decision_ctx.upper():
        # Allow OBSERVE decision only when lifecycle also non-directional / candidate exported separately.
        if life_ctx.upper() in {"LONG_CONTEXT", "SHORT_CONTEXT"} and decision_ctx.upper() not in {
            "LONG_CONTEXT",
            "SHORT_CONTEXT",
        }:
            matches = False
            mismatch_reason = f"decision={decision_ctx} lifecycle={life_ctx}"

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
            "decision_built_after_lifecycle_refresh": True,
            "lifecycle_row_reloaded_after_refresh": lifecycle_reloaded,
            "final_context_row_reloaded_after_refresh": final_reloaded,
            "decision_context_matches_lifecycle": matches,
            "decision_context_mismatch_reason": mismatch_reason,
        }

    append_result = logger_mod.append_decision(row, log_path=decision_log)
    return {
        "refresh_performed": True,
        "decision_log_append_performed": True,
        "appended_rows_count": 1,
        "append_result": append_result,
        "refresh_result": refresh_result,
        "decision_built_after_lifecycle_refresh": True,
        "lifecycle_row_reloaded_after_refresh": lifecycle_reloaded,
        "final_context_row_reloaded_after_refresh": final_reloaded,
        "decision_context_matches_lifecycle": matches,
        "decision_context_mismatch_reason": mismatch_reason,
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


def _fill_after_decision_ok(
    *,
    decision: dict[str, Any],
    execution_ts: Any,
) -> dict[str, Any]:
    """Point-in-time fill guard: decision_timestamp < fill_timestamp."""
    decision_ts = _first_ts_value(
        decision.get("candle_timestamp"),
        decision.get("latest_decision_log_ts"),
        decision.get("decision_log_ts"),
        decision.get("source_context_ts"),
    )
    fill_ts = _first_ts_value(execution_ts)
    if decision_ts is None or fill_ts is None:
        return {
            "ok": False,
            "reason": "NO_FILL_MISSING_TIMESTAMPS",
            "decision_timestamp": decision_ts,
            "fill_timestamp": fill_ts,
        }
    d = pd.Timestamp(decision_ts)
    f = pd.Timestamp(fill_ts)
    if f.tzinfo is None:
        f = f.tz_localize("UTC")
    else:
        f = f.tz_convert("UTC")
    if d.tzinfo is None:
        d = d.tz_localize("UTC")
    else:
        d = d.tz_convert("UTC")
    if not (f > d):
        return {
            "ok": False,
            "reason": "NO_FILL_FILL_NOT_AFTER_DECISION",
            "decision_timestamp": d.isoformat().replace("+00:00", "Z"),
            "fill_timestamp": f.isoformat().replace("+00:00", "Z"),
        }
    return {
        "ok": True,
        "reason": None,
        "decision_timestamp": d.isoformat().replace("+00:00", "Z"),
        "fill_timestamp": f.isoformat().replace("+00:00", "Z"),
    }


def run_one_cycle(
    *,
    root: Path,
    cycle_idx: int,
    skip_refresh: bool = DEFAULT_SKIP_REFRESH,
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

    # Fresh market snapshot for any ENTRY/EXIT fill decision (not process health).
    snap = fetch_cycle_market_snapshot(max_age_seconds=90.0)
    result.update(market_snapshot_fields(snap))
    # Phase-1 diagnostics only: never use origin as fill; eligibility unchanged.
    origin_diag = extract_context_price_diagnostics(
        decision,
        execution_observation_price=_sf(snap.get("price")) if snap else None,
    )
    result.update(
        {
            "context_reference_price": origin_diag.get("context_reference_price"),
            "context_reference_timestamp": origin_diag.get("context_reference_timestamp"),
            "context_episode_id": origin_diag.get("context_episode_id"),
            "execution_observation_price": origin_diag.get("execution_observation_price"),
            "distance_from_context_bps": origin_diag.get("distance_from_context_bps"),
            "entry_price_source": (
                None
                if not bool(snap.get("available"))
                else str(snap.get("source") or "MARKET_SNAPSHOT")
            ),
        }
    )
    try:
        from paper_policy_engine import (
            EXIT_PENDING_MARKET_DATA_UNAVAILABLE,
            MARKET_DATA_SNAPSHOT_UNAVAILABLE,
        )
    except Exception:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paper_policy_engine import (
            EXIT_PENDING_MARKET_DATA_UNAVAILABLE,
            MARKET_DATA_SNAPSHOT_UNAVAILABLE,
        )

    if opens:
        pos = opens[0]
        # Use fresh snapshot price when available; never silently invent exit price.
        if bool(snap.get("available")) and snap.get("price") is not None:
            mark_px = float(snap["price"])
            exit_preview = evaluate_exit_preview(
                side=pos["side"],
                entry_price=pos["entry_price"],
                quantity=pos["quantity_btc"],
                stop_loss_price=pos["stop_loss_price"],
                take_profit_price=pos["take_profit_price"],
                entry_fee_usd=pos["entry_fee_usd"],
                current_price=mark_px,
                latest_high=mark_px,
                latest_low=mark_px,
                latest_context=str(decision.get("active_market_context") or ""),
                latest_lifecycle_state=str(decision.get("lifecycle_state") or ""),
                hold_mode=PAPER_CONTEXT_HOLD_MODE,
            )
        else:
            # Diagnostic mark from M15 only for hold preview; close blocked without snapshot.
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
                hold_mode=PAPER_CONTEXT_HOLD_MODE,
            )
        result["exit_preview_action"] = exit_preview["exit_preview_action"]
        result["pnl_bps"] = exit_preview["unrealized_pnl_bps"]
        result["pnl_usd"] = exit_preview["unrealized_pnl_usd"]
        result["position_id"] = pos["position_id"]
        result["entry_price"] = pos["entry_price"]

        if exit_preview["is_hold"]:
            result["action_taken"] = "OBSERVE_HOLD"
            result["reason"] = exit_preview["exit_preview_reason"]
        elif not bool(snap.get("available")) or snap.get("price") is None:
            result["action_taken"] = "EXIT_PENDING"
            result["reason"] = EXIT_PENDING_MARKET_DATA_UNAVAILABLE
            result["exit_preview_action"] = EXIT_PENDING_MARKET_DATA_UNAVAILABLE
        else:
            # Force fill at fresh snapshot price for market-style exits.
            exit_preview = dict(exit_preview)
            if "STOP_LOSS" not in str(exit_preview.get("exit_preview_action") or "") and "TAKE_PROFIT" not in str(
                exit_preview.get("exit_preview_action") or ""
            ):
                exit_preview["suggested_exit_price"] = float(snap["price"])
            written = write_close_position_chain(
                research=research,
                open_pos=pos,
                exit_preview=exit_preview,
                decision=decision,
                market=market,
                market_snapshot=snap,
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
        previous = load_previous_decision(live, before_ts=decision.get("candle_timestamp"))
        try:
            from paper_policy_engine import mark_context_episode_traded
            from paper_traded_context_episode_memory import load_traded_episode_memory, write_traded_episode_memory
        except Exception:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from paper_policy_engine import mark_context_episode_traded
            from paper_traded_context_episode_memory import load_traded_episode_memory, write_traded_episode_memory
        mem_path = traded_episode_memory_path(research)
        episode_memory = load_traded_episode_memory(mem_path)
        gate = evaluate_flat_entry_gate(
            decision,
            previous_decision=previous,
            traded_episode_memory=episode_memory,
            position_already_open=False,
        )
        if not allow_open or not gate["allowed"]:
            result["action_taken"] = "OBSERVE_NO_TRADE"
            result["reason"] = (
                "open_disabled"
                if not allow_open
                else ",".join(gate["block_reasons"]) or "no_trade"
            )
        elif not bool(snap.get("available")) or snap.get("price") is None:
            result["action_taken"] = "OBSERVE_NO_TRADE"
            result["reason"] = MARKET_DATA_SNAPSHOT_UNAVAILABLE
        else:
            side = str(gate["side"])
            execution = resolve_entry_execution_observation(decision, snap)
            if not execution.get("available"):
                result["action_taken"] = "NO_FILL"
                result["reason"] = execution.get("reason") or "ENTRY_BLOCKED_NO_ATOMIC_EXECUTION_PRICE"
            else:
                px = float(execution["price"])
                if abs(px - SYNTHETIC_FORBIDDEN_PRICE) < 1e-9:
                    result["action_taken"] = "NO_FILL"
                    result["reason"] = "live_price_unavailable_or_synthetic"
                else:
                    fill_guard = _fill_after_decision_ok(
                        decision=decision,
                        execution_ts=execution.get("execution_ts"),
                    )
                    if not fill_guard.get("ok"):
                        result["action_taken"] = "NO_FILL"
                        result["reason"] = str(fill_guard.get("reason") or "NO_FILL")
                        result["fill_guard"] = fill_guard
                    else:
                        sizing = resolve_entry_risk_sizing(
                            side=side,
                            entry_price=px,
                            stop_loss_price=decision.get("stop_loss_price"),
                            take_profit_price=decision.get("take_profit_price"),
                        )
                        if not sizing.get("allowed"):
                            result["action_taken"] = "NO_ORDER"
                            result["reason"] = str(
                                sizing.get("reason") or "INVALID_STOP_DISTANCE"
                            )
                        else:
                            entry_src = str(
                                execution["entry_execution_source"]
                                or execution["source"]
                                or "UNKNOWN_EXECUTION_SOURCE"
                            )
                            entry_execution_ts = str(execution["execution_ts"])
                            written = write_open_position_chain(
                                research=research,
                                decision=decision,
                                side=side,
                                entry_price=float(px),
                                entry_price_source=entry_src,
                                market_ts=entry_execution_ts,
                                market_snapshot=snap,
                                policy_tags=gate,
                                entry_execution_ts=entry_execution_ts,
                                sizing=sizing,
                            )
                            open_reason = (
                                "context_start_event_open"
                                if bool(gate.get("context_start_event"))
                                else "active_directional_context_open"
                            )
                            # One-trade-per-context memory (paper-only JSON; not a ledger parquet).
                            episode_key = str(gate.get("context_episode_key") or "")
                            if episode_key:
                                updated_mem = mark_context_episode_traded(
                                    episode_memory,
                                    episode_key=episode_key,
                                    side=side,
                                    context=str(gate.get("current_context") or ""),
                                    trade_id=written.get("trade_id"),
                                    signal_id=written.get("signal_id"),
                                    entry_ts=str(
                                        written.get("entry_ts") or entry_execution_ts
                                    ),
                                )
                                write_traded_episode_memory(mem_path, updated_mem)
                            result.update(
                                {
                                    "action_taken": f"OPEN_{side}",
                                    "reason": open_reason,
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
                                    "reason": open_reason,
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
            "market_snapshot_source": result.get("market_snapshot_source"),
            "market_snapshot_observed_at": result.get("market_snapshot_observed_at"),
            "market_snapshot_age_seconds": result.get("market_snapshot_age_seconds"),
            "market_snapshot_fallback_used": result.get("market_snapshot_fallback_used"),
            "market_snapshot_warning": result.get("market_snapshot_warning"),
            "market_snapshot_available": result.get("market_snapshot_available"),
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
    skip_refresh: bool = DEFAULT_SKIP_REFRESH,
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
    # Patch 2B.2: read-only consumer by default. Context refresh is opt-in only.
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        default=DEFAULT_SKIP_REFRESH,
        help="Do not refresh context/decision plane (default: true)",
    )
    parser.add_argument(
        "--enable-context-refresh",
        action="store_true",
        help="DANGEROUS legacy: allow paper to trigger context refresh + decision append",
    )
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

    skip_refresh = True
    if bool(args.enable_context_refresh):
        skip_refresh = False
    elif bool(args.skip_refresh):
        skip_refresh = True

    return run_controller(
        root=args.root.resolve(),
        max_cycles=max(1, int(args.max_cycles)),
        interval_seconds=max(0, int(args.interval_seconds)),
        max_duration_hours=float(args.max_duration_hours),
        skip_refresh=skip_refresh,
        one_cycle=bool(args.one_cycle),
        background_safe=bool(args.background_safe),
    )


if __name__ == "__main__":
    raise SystemExit(main())
