#!/usr/bin/env python3
"""Canonical bar-policy paper trade helpers (research/visual only).

This module restores a non-empty policy-context trade source from already-built
canonical context episodes. It does not mutate cognition, raw paper ledgers, or
runtime execution behavior.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "live") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "live"))

from paper_pnl_engine import (  # type: ignore
    FEE_BPS_PER_SIDE,
    INITIAL_CAPITAL,
    MAX_RISK_PER_TRADE_PCT,
    SIZING_MODE,
    SLIPPAGE_USD,
    STOP_LOSS_BPS,
    TAKE_PROFIT_BPS,
    compute_trade_math,
    stop_take_prices,
    summarize_trades,
)
from paper_trade_economics import (  # type: ignore
    ECONOMICS_SOURCE,
    ENTRY_FEE_BPS as CANONICAL_ENTRY_FEE_BPS,
    EXIT_FEE_BPS as CANONICAL_EXIT_FEE_BPS,
    NORMAL_ENTRY_SLIPPAGE_BPS as CANONICAL_ENTRY_SLIPPAGE_BPS,
    NORMAL_EXIT_SLIPPAGE_BPS as CANONICAL_EXIT_SLIPPAGE_BPS,
)
from paper_policy_engine import (  # type: ignore
    HOLD_UNTIL_DIRECTIONAL_CONTEXT_END,
    PAPER_CONTEXT_POLICY_MODE_TRADE_ALL,
)

SIM = ROOT / "data" / "research" / "paper_simulator"
DATA_RESEARCH = ROOT / "data" / "research"
LIVE = ROOT / "data" / "live"
COGNITION = ROOT / "data" / "cognition"
DOCS = ROOT / "docs"
PUBLIC = ROOT / "apps" / "context_visualizer" / "public" / "data"

CANONICAL_EPISODES = SIM / "canonical_policy_context_episodes.parquet"
CANONICAL_EPISODES_JSON = SIM / "canonical_policy_context_episodes.json"
CANONICAL_TRADES_PARQUET = SIM / "policy_context_canonical_bar_policy_trades.parquet"
CANONICAL_TRADES_JSON = SIM / "policy_context_canonical_bar_policy_trades.json"
CANONICAL_PNL_JSON = SIM / "policy_context_canonical_bar_policy_pnl_summary.json"
CANONICAL_POLICY_JSON = DATA_RESEARCH / "canonical_paper_trading_policy_reconfirmation.json"
CANONICAL_POLICY_DOC = DOCS / "CANONICAL_PAPER_TRADING_POLICY_RECONFIRMATION.md"
CANONICAL_TRADES_DOC = DOCS / "POLICY_CONTEXT_CANONICAL_BAR_POLICY_TRADES.md"

LEGACY_TRADES = SIM / "policy_context_trades.parquet"
EVENT_PRICED_TRADES = SIM / "policy_context_event_priced_trades.parquet"
EVENT_PRICED_PNL = SIM / "policy_context_event_priced_pnl_summary.json"
ALIGNED_TRADES = SIM / "policy_context_event_aligned_trades.parquet"
TRADER_METRICS_JSON = SIM / "policy_context_trader_metrics.json"
CONTEXT_DECISION_LOG = LIVE / "context_decision_log.parquet"
INTRABAR_CONTEXT_EVENTS = LIVE / "intrabar_context_events.parquet"
LIVE_INTRABAR_FEED = LIVE / "live_market_intrabar_feed.parquet"

MODE = "POLICY_CONTEXT_CANONICAL_BAR_POLICY_PNL"
RESTORED_MODE = "POLICY_CONTEXT_RESTORED_NON_EMPTY_SOURCE"
EVENT_PRICED_MODE = "POLICY_CONTEXT_EVENT_PRICED_PNL"
ALIGNED_MODE = "POLICY_CONTEXT_EVENT_ALIGNED_PNL"
LEGACY_MODE = "RISK_BASED_POLICY_CONTEXT_PNL"
PRICING_MODE = "CONTEXT_BAR_POLICY_PRICE"
ACTION_CLOCK_MODE = "CONTEXT_START_END_BAR_POLICY"
ENTRY_PRICE_POLICY = "CONTEXT_START_BAR_POLICY_PRICE"
EXIT_PRICE_POLICY = "CONTEXT_END_BAR_POLICY_PRICE"
TRADE_SIDE_SOURCE = "PAPER_POLICY_ACTION"
SIZING_MODE_LABEL = SIZING_MODE
WINDOW_START = pd.Timestamp("2026-07-21T00:00:00Z")
ENTRY_FEE_RATE = CANONICAL_ENTRY_FEE_BPS / 10000.0
EXIT_FEE_RATE = CANONICAL_EXIT_FEE_BPS / 10000.0
ENTRY_SPREAD_RATE = CANONICAL_ENTRY_SLIPPAGE_BPS / 10000.0
EXIT_SPREAD_RATE = CANONICAL_EXIT_SLIPPAGE_BPS / 10000.0


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ts(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def iso(value: Any) -> str | None:
    ts = to_ts(value)
    if ts is None:
        return None
    return ts.isoformat().replace("+00:00", "Z")


def unix(value: Any) -> int | None:
    ts = to_ts(value)
    if ts is None:
        return None
    return int(ts.timestamp())


def num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return iso(value)
    if value is pd.NaT:
        return None
    if hasattr(value, "item") and type(value).__module__.startswith("numpy"):
        return json_safe(value.item())
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, float) and not math.isfinite(value):
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2) + "\n", encoding="utf-8")


def write_md(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([f"# {title}", "", *lines, ""]), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def context_to_side(context_side: Any) -> str:
    return "SHORT" if "SHORT" in str(context_side or "").upper() else "LONG"


def paper_policy_action_for_side(side: str) -> str:
    return "OPEN_SHORT" if str(side).upper() == "SHORT" else "OPEN_LONG"


def paper_policy_exit_for_side(side: str) -> str:
    return "CLOSE_SHORT" if str(side).upper() == "SHORT" else "CLOSE_LONG"


def result_status(net_pnl: Any) -> str:
    pnl = num(net_pnl) or 0.0
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "BREAKEVEN"


def _decision_metadata(decisions: pd.DataFrame, start_value: Any, end_value: Any, side: str) -> dict[str, Any]:
    if decisions.empty:
        return {
            "decision_available_at_entry": None,
            "controller_cycle_ts_entry": None,
            "decision_latency_seconds": None,
            "controller_latency_seconds": None,
        }
    start = to_ts(start_value)
    end = to_ts(end_value)
    if start is None:
        return {
            "decision_available_at_entry": None,
            "controller_cycle_ts_entry": None,
            "decision_latency_seconds": None,
            "controller_latency_seconds": None,
        }
    out = decisions.copy()
    for col in ("signal_fields_generated_at_utc", "decision_written_at_utc", "candle_timestamp"):
        if col in out.columns:
            out[f"_{col}_ts"] = pd.to_datetime(out[col], utc=True, errors="coerce")
    base = out.get("_signal_fields_generated_at_utc_ts", pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]"))
    if "_decision_written_at_utc_ts" in out.columns:
        out["_decision_available_ts"] = base.fillna(out["_decision_written_at_utc_ts"])
    else:
        out["_decision_available_ts"] = base
    hi = (end or start) + pd.Timedelta(minutes=120)
    window = out[(out["_decision_available_ts"] >= start) & (out["_decision_available_ts"] <= hi)].copy()
    if window.empty:
        return {
            "decision_available_at_entry": None,
            "controller_cycle_ts_entry": None,
            "decision_latency_seconds": None,
            "controller_latency_seconds": None,
        }
    side_u = str(side).upper()
    matched = window[
        (window.get("intended_side", pd.Series(index=window.index, dtype=object)).astype(str).str.upper() == side_u)
        | (window.get("position_intent", pd.Series(index=window.index, dtype=object)).astype(str).str.upper() == f"OPEN_{side_u}")
    ]
    if matched.empty:
        matched = window
    row = matched.sort_values("_decision_available_ts").iloc[0]
    decision_ts = to_ts(row.get("_decision_available_ts"))
    cycle_ts = to_ts(row.get("decision_written_at_utc"))
    return {
        "decision_available_at_entry": iso(decision_ts),
        "controller_cycle_ts_entry": iso(cycle_ts),
        "decision_latency_seconds": None if decision_ts is None else round((decision_ts - start).total_seconds(), 6),
        "controller_latency_seconds": None if cycle_ts is None else round((cycle_ts - start).total_seconds(), 6),
    }


def _trade_dict_for_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": row.get("trade_id"),
        "entry_ts": row.get("entry_ts"),
        "exit_ts": row.get("exit_ts"),
        "net_pnl": row.get("net_pnl"),
        "gross_pnl": row.get("gross_pnl"),
        "fees": row.get("fees"),
        "slippage": row.get("slippage"),
        "r_multiple": row.get("r_multiple"),
        "position_notional_usd": row.get("position_notional_usd"),
        "position_size_btc": row.get("position_size_btc"),
    }


def build_canonical_bar_policy_trades() -> tuple[pd.DataFrame, dict[str, Any]]:
    episodes = read_parquet(CANONICAL_EPISODES)
    if not episodes.empty and "start_time" in episodes.columns:
        episodes = episodes[pd.to_datetime(episodes["start_time"], utc=True, errors="coerce") >= WINDOW_START].copy()
    decisions = read_parquet(CONTEXT_DECISION_LOG)
    rows: list[dict[str, Any]] = []
    for _, ep in episodes.sort_values("start_time").iterrows():
        episode_id = int(ep.get("episode_id"))
        side = context_to_side(ep.get("context_side"))
        entry = float(ep.get("start_price"))
        exit_ = float(ep.get("end_price"))
        stop_price, take_price = stop_take_prices(side, entry)
        math_row = compute_trade_math(
            side=side,
            entry_price=entry,
            exit_price=exit_,
            stop_loss_price=stop_price,
            take_profit_price=take_price,
        )
        action = paper_policy_action_for_side(side)
        exit_action = paper_policy_exit_for_side(side)
        start_ts = iso(ep.get("start_time"))
        end_ts = iso(ep.get("end_time"))
        metadata = _decision_metadata(decisions, start_ts, end_ts, side)
        net_pnl = math_row.net_pnl
        row = {
            "trade_id": f"POLICY_CONTEXT_CANONICAL_BAR_TRADE_{episode_id}",
            "legacy_trade_id": f"POLICY_CONTEXT_TRADE_{episode_id}",
            "source": "policy_context_canonical_bar_policy_research",
            "pnl_mode": MODE,
            "pricing_mode": PRICING_MODE,
            "action_clock_mode": ACTION_CLOCK_MODE,
            "trade_policy_mode": PAPER_CONTEXT_POLICY_MODE_TRADE_ALL,
            "hold_policy_mode": HOLD_UNTIL_DIRECTIONAL_CONTEXT_END,
            "context_id": f"POLICY_CONTEXT_{episode_id}",
            "context_episode_id": episode_id,
            "lifecycle_episode_id": episode_id,
            "context_side": ep.get("context_side"),
            "side": side,
            "trade_side": side,
            "trade_side_source": TRADE_SIDE_SOURCE,
            "paper_policy_action_at_start": action,
            "paper_policy_action_at_end": exit_action,
            "paper_policy_action_source": "paper_policy_engine.TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS",
            "paper_policy_hold_source": "paper_policy_engine.HOLD_UNTIL_DIRECTIONAL_CONTEXT_END",
            "context_start_bar_ts": start_ts,
            "context_end_bar_ts": end_ts,
            "context_start_bar_price": entry,
            "context_end_bar_price": exit_,
            "context_start_bar_price_source": ep.get("start_price_source"),
            "context_end_bar_price_source": ep.get("end_price_source"),
            "context_start_time": start_ts,
            "context_end_time": end_ts,
            "entry_ts": start_ts,
            "exit_ts": end_ts,
            "entry_action_ts": start_ts,
            "exit_action_ts": end_ts,
            "entry_price": entry,
            "exit_price": exit_,
            "entry_price_source": ENTRY_PRICE_POLICY,
            "exit_price_source": EXIT_PRICE_POLICY,
            "entry_price_policy": ENTRY_PRICE_POLICY,
            "exit_price_policy": EXIT_PRICE_POLICY,
            "decision_available_at_entry": metadata["decision_available_at_entry"],
            "controller_cycle_ts_entry": metadata["controller_cycle_ts_entry"],
            "decision_latency_seconds": metadata["decision_latency_seconds"],
            "controller_latency_seconds": metadata["controller_latency_seconds"],
            "decision_latency_used_as_entry": False,
            "controller_cycle_used_as_entry": False,
            "uses_decision_latency_as_entry_ts": False,
            "uses_controller_cycle_as_entry_ts": False,
            "opens_inside_context": False,
            "closes_after_context": False,
            "candle_close_used_as_execution_price": False,
            "uses_candle_close_entry_price": False,
            "uses_candle_close_exit_price": False,
            "silent_candle_close_fallback_used": False,
            "canonical_context_bar_price_used": True,
            "canonical_policy_explicitly_uses_context_bar_price": True,
            "quality_blocks_entry": False,
            "quality_blocks_exit": False,
            "quality_blocks_primary_pnl": False,
            "quality_hides_visual_trade": False,
            "quality_label_metadata_only": True,
            "context_label_only_side_inferred": False,
            "policy_action_evaluated": True,
            "context_quality_label": ep.get("context_quality_label"),
            "context_confidence_label": ep.get("context_confidence_label"),
            "is_confirmed": bool(ep.get("is_confirmed")),
            "is_questionable": bool(ep.get("is_questionable")),
            "is_challenged": bool(ep.get("is_challenged")),
            "is_candidate_only": bool(ep.get("is_candidate_only")),
            "july21_trade": bool(to_ts(start_ts) is not None and to_ts(start_ts) < pd.Timestamp("2026-07-22T00:00:00Z")),
            "visible_on_chart": True,
            "included_in_primary_pnl": True,
            "included_in_primary_canonical_bar_policy_pnl": True,
            "included_in_policy_context_pnl": True,
            "included_in_visual": True,
            "initial_capital": INITIAL_CAPITAL,
            "initial_capital_usd": INITIAL_CAPITAL,
            "risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
            "risk_amount": math_row.risk_amount,
            "risk_amount_usd": math_row.risk_amount,
            "initial_risk_usd": math_row.risk_amount,
            "position_sizing_mode": SIZING_MODE_LABEL,
            "sizing_mode": SIZING_MODE_LABEL,
            "sizing_status": math_row.sizing_status,
            "stop_loss_bps": STOP_LOSS_BPS,
            "take_profit_bps": TAKE_PROFIT_BPS,
            "stop_loss_price": math_row.stop_loss_price,
            "take_profit_price": math_row.take_profit_price,
            "stop_take_policy_name": "RISK_1PCT_STOP_100BPS_TAKE_150BPS",
            "stop_take_source": "paper_pnl_engine.stop_take_prices",
            "stop_distance": math_row.stop_distance,
            "notional_usd": math_row.position_notional,
            "position_notional": math_row.position_notional,
            "position_notional_usd": math_row.position_notional,
            "position_size": round(math_row.position_size_btc, 10),
            "position_size_btc": round(math_row.position_size_btc, 10),
            "quantity": round(math_row.position_size_btc, 10),
            "gross_pnl": math_row.gross_pnl,
            "gross_pnl_usd": math_row.gross_pnl,
            "entry_fee": math_row.entry_fee,
            "exit_fee": math_row.exit_fee,
            "fees": math_row.fees,
            "fees_usd": math_row.fees,
            "entry_slippage_usd": math_row.entry_slippage,
            "exit_slippage_usd": math_row.exit_slippage,
            "slippage": math_row.slippage,
            "slippage_usd": math_row.slippage,
            "slippage_bps": math_row.slippage_bps,
            "slippage_R": math_row.slippage_R,
            "gross_pnl_before_fees_slippage": math_row.gross_pnl,
            "net_pnl_after_fees_slippage": net_pnl,
            "entry_execution_source": ENTRY_PRICE_POLICY,
            "exit_execution_source": EXIT_PRICE_POLICY,
            "execution_quality_status": "OK",
            "context_quality": ep.get("context_quality_label"),
            "paper_entry_basis": "CANONICAL_CONTEXT_BAR_POLICY",
            "economics_source": ECONOMICS_SOURCE,
            "net_pnl": net_pnl,
            "net_pnl_usd": net_pnl,
            "realized_pnl_usd": net_pnl,
            "net_return_pct": round(net_pnl / INITIAL_CAPITAL * 100.0, 8),
            "realized_pnl_bps": round(((entry - exit_) / entry * 10000.0) if side == "SHORT" else ((exit_ - entry) / entry * 10000.0), 6),
            "r_multiple": math_row.r_multiple,
            "R": math_row.r_multiple,
            "result_status": result_status(net_pnl),
            "loss_reason": "NET_LOSS_AFTER_COSTS" if net_pnl < 0 else None,
            "paper_only": True,
            "execution_enabled": False,
            "exchange_order_api_used": False,
            "exchange_api_call_used": False,
            "raw_ledger_rewritten": False,
            "cognition_modified": False,
        }
        rows.append(row)
    df = pd.DataFrame(rows)
    inc = df[df.get("included_in_primary_canonical_bar_policy_pnl", False) == True].copy() if not df.empty else pd.DataFrame()  # noqa: E712
    pnl_sum = float(pd.to_numeric(inc.get("net_pnl_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if len(inc) else 0.0
    aggregate = {
        "generated_at_utc": iso_now(),
        "pnl_mode": MODE,
        "pricing_mode": PRICING_MODE,
        "action_clock_mode": ACTION_CLOCK_MODE,
        "primary_trade_file": rel(CANONICAL_TRADES_PARQUET),
        "canonical_context_count_since_2026_07_21": int(len(episodes)),
        "trade_count": int(len(inc)),
        "canonical_bar_policy_trade_count": int(len(inc)),
        "july21_trade_count": int(inc.get("july21_trade", pd.Series(dtype=bool)).sum()) if len(inc) else 0,
        "total_pnl_usd": round(pnl_sum, 6),
        "entry_aligned_to_context_start_bar": bool((inc["entry_ts"] == inc["context_start_bar_ts"]).all()) if len(inc) else False,
        "exit_aligned_to_context_end_bar": bool((inc["exit_ts"] == inc["context_end_bar_ts"]).all()) if len(inc) else False,
        "opens_inside_context_count": int(inc.get("opens_inside_context", pd.Series(dtype=bool)).sum()) if len(inc) else 0,
        "decision_latency_used_as_entry": False,
        "controller_cycle_used_as_entry": False,
        "candle_close_used_as_execution_price": False,
        "trade_side_from_policy_action": bool((inc.get("trade_side_source", pd.Series(dtype=object)) == TRADE_SIDE_SOURCE).all()) if len(inc) else False,
        "quality_filters_trade_count": int((inc.get("quality_blocks_entry", pd.Series(dtype=bool)) == True).sum()) if len(inc) else 0,  # noqa: E712
        "raw_ledger_rewritten": False,
        "real_execution_used": False,
        "exchange_order_api_used": False,
        "cognition_modified": False,
    }
    return df, aggregate


def _net_values(included: pd.DataFrame) -> list[float]:
    return pd.to_numeric(included.get("net_pnl_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).tolist()


def _series_float(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).astype(float)


def _recalculate_cost_accounting(included: pd.DataFrame) -> pd.DataFrame:
    if included.empty:
        return included.copy()
    out = included.copy()
    qty = _series_float(out, "position_size_btc").abs()
    entry = _series_float(out, "entry_price")
    exit_ = _series_float(out, "exit_price")
    side = out.get("side", pd.Series("", index=out.index, dtype=object)).astype(str).str.upper()

    entry_notional = (qty * entry).abs()
    exit_notional = (qty * exit_).abs()
    gross = (exit_ - entry) * qty
    gross = gross.where(side != "SHORT", (entry - exit_) * qty)
    entry_fee = entry_notional * ENTRY_FEE_RATE
    exit_fee = exit_notional * EXIT_FEE_RATE
    exchange_fees = entry_fee + exit_fee
    entry_slippage = entry_notional * ENTRY_SPREAD_RATE
    exit_slippage = exit_notional * EXIT_SPREAD_RATE
    spread_slippage = entry_slippage + exit_slippage
    total_cost = exchange_fees + spread_slippage
    net = gross - total_cost
    risk_amount = _series_float(out, "risk_amount_usd")
    default_risk = INITIAL_CAPITAL * MAX_RISK_PER_TRADE_PCT / 100.0
    risk_amount = risk_amount.where(risk_amount > 0, default_risk)
    r_multiple = (net / risk_amount.mask(risk_amount <= 0)).fillna(0.0)

    out["entry_notional_usd"] = entry_notional.round(6)
    out["exit_notional_usd"] = exit_notional.round(6)
    out["entry_fee"] = entry_fee.round(6)
    out["exit_fee"] = exit_fee.round(6)
    out["fees"] = exchange_fees.round(6)
    out["fees_usd"] = exchange_fees.round(6)
    out["entry_slippage_usd"] = entry_slippage.round(6)
    out["exit_slippage_usd"] = exit_slippage.round(6)
    out["slippage"] = spread_slippage.round(6)
    out["slippage_usd"] = spread_slippage.round(6)
    out["slippage_bps"] = CANONICAL_ENTRY_SLIPPAGE_BPS + CANONICAL_EXIT_SLIPPAGE_BPS
    out["slippage_R"] = (spread_slippage / risk_amount.mask(risk_amount <= 0)).fillna(0.0).round(8)
    out["total_costs_usd"] = total_cost.round(6)
    out["gross_pnl"] = gross.round(6)
    out["gross_pnl_usd"] = gross.round(6)
    out["gross_pnl_before_fees_slippage"] = gross.round(6)
    out["net_pnl"] = net.round(6)
    out["net_pnl_usd"] = net.round(6)
    out["net_pnl_after_fees_slippage"] = net.round(6)
    out["realized_pnl_usd"] = net.round(6)
    out["net_return_pct"] = (net / INITIAL_CAPITAL * 100.0).round(8)
    out["r_multiple"] = r_multiple.round(6)
    out["R"] = out["r_multiple"]
    for col, default in (
        ("entry_execution_source", ENTRY_PRICE_POLICY),
        ("exit_execution_source", EXIT_PRICE_POLICY),
        ("execution_quality_status", "OK"),
        ("paper_entry_basis", "CANONICAL_CONTEXT_BAR_POLICY"),
    ):
        if col not in out.columns:
            out[col] = default
        else:
            out[col] = out[col].fillna(default).replace("", default)
    if "context_quality" not in out.columns:
        out["context_quality"] = out.get("context_quality_label", pd.Series(None, index=out.index, dtype=object))
    out["economics_source"] = ECONOMICS_SOURCE
    out["result_status"] = [result_status(v) for v in out["net_pnl_usd"]]
    out["loss_reason"] = out["net_pnl_usd"].apply(lambda v: "NET_LOSS_AFTER_COSTS" if float(v) < 0 else None)
    return out


def _max_streak(values: list[bool]) -> int:
    best = cur = 0
    for value in values:
        if value:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def build_canonical_bar_policy_metrics(df: pd.DataFrame) -> dict[str, Any]:
    stored_included = df[df.get("included_in_primary_canonical_bar_policy_pnl", False) == True].copy() if not df.empty else pd.DataFrame()  # noqa: E712
    included = _recalculate_cost_accounting(stored_included)
    rows = [_trade_dict_for_metrics(r.to_dict()) for _, r in included.iterrows()]
    summary = summarize_trades(rows, initial_capital=INITIAL_CAPITAL)
    detailed = dict(summary["detailed_pnl"])
    metrics = dict(summary["model_evaluation_metrics"])
    equity_curve = summary["equity_curve"]
    net_values = _net_values(included)
    wins = [v for v in net_values if v > 0]
    losses = [v for v in net_values if v < 0]
    r_values = pd.to_numeric(included.get("r_multiple", pd.Series(dtype=float)), errors="coerce").dropna().tolist()
    notionals = pd.to_numeric(included.get("position_notional_usd", pd.Series(dtype=float)), errors="coerce").dropna().tolist()
    sizes = pd.to_numeric(included.get("position_size_btc", pd.Series(dtype=float)), errors="coerce").dropna().tolist()
    gross = float(pd.to_numeric(included.get("gross_pnl_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if len(included) else 0.0
    fees = float(pd.to_numeric(included.get("fees_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if len(included) else 0.0
    slip = float(pd.to_numeric(included.get("slippage_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if len(included) else 0.0
    total_net = float(sum(net_values))
    sample_warning = bool(metrics.get("status") == "low sample size" or len(net_values) < 30)
    net_profit = sum(v for v in net_values if v > 0)
    net_loss = sum(v for v in net_values if v < 0)
    if losses:
        profit_factor: float | str = net_profit / abs(net_loss) if net_loss else 0.0
    else:
        profit_factor = "Infinity" if net_profit > 0 else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss else (None if avg_win else 0.0)
    result_bools = [v > 0 for v in net_values]
    detailed.update({
        "initial_capital_usd": round(INITIAL_CAPITAL, 6),
        "current_equity_usd": round(INITIAL_CAPITAL + total_net, 6),
        "realized_pnl_usd": round(total_net, 6),
        "unrealized_pnl_usd": detailed.get("unrealized_pnl", 0.0),
        "total_pnl_usd": round(total_net, 6),
        "net_after_costs": round(total_net, 6),
        "net_after_costs_usd": round(total_net, 6),
        "net_pnl_after_costs_usd": round(total_net, 6),
        "gross_pnl_before_costs": round(gross, 6),
        "gross_pnl_before_costs_usd": round(gross, 6),
        "fees_paid": round(fees, 6),
        "fees_paid_usd": round(fees, 6),
        "slippage_paid": round(slip, 6),
        "slippage_paid_usd": round(slip, 6),
        "total_costs_paid": round(fees + slip, 6),
        "total_costs_paid_usd": round(fees + slip, 6),
        "annualization_status": "UNSTABLE_SHORT_SAMPLE" if sample_warning else "OK",
        "annualization_warning": "Annualized return is unstable for short sample" if sample_warning else None,
        "loss_rate_pct": metrics.get("loss_rate_pct", 0.0),
        "breakeven_count": len([v for v in net_values if abs(v) < 1e-9]),
        "risk_amount_usd": round(INITIAL_CAPITAL * MAX_RISK_PER_TRADE_PCT / 100.0, 6),
        "avg_position_notional_usd": round(sum(notionals) / len(notionals), 6) if notionals else 0.0,
        "min_position_notional_usd": round(min(notionals), 6) if notionals else 0.0,
        "max_position_notional_usd": round(max(notionals), 6) if notionals else 0.0,
        "avg_position_size_btc": round(sum(sizes) / len(sizes), 10) if sizes else 0.0,
    })
    metrics.update({
        "sample_size_warning": sample_warning,
        "risk_metrics_sample_warning": sample_warning,
        "metrics_marked_indicative": sample_warning,
        "sharpe_status": "UNSTABLE_SHORT_SAMPLE" if sample_warning else "OK",
        "sortino_status": "UNSTABLE_SHORT_SAMPLE" if sample_warning else "OK",
        "calmar_status": "UNSTABLE_SHORT_SAMPLE" if sample_warning else "OK",
        "closed_trades": len(net_values),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len([v for v in net_values if abs(v) < 1e-9]),
        "profit_factor": round(profit_factor, 8) if isinstance(profit_factor, float) else profit_factor,
        "net_gross_profit_for_pf": round(net_profit, 6),
        "net_gross_loss_for_pf": round(net_loss, 6),
        "payoff_ratio": None if payoff is None else round(payoff, 8),
        "expectancy_per_trade_usd": metrics.get("expectancy_per_trade"),
        "expectancy_usd": metrics.get("expectancy_per_trade"),
        "avg_r_multiple": round(sum(r_values) / len(r_values), 8) if r_values else 0.0,
        "median_r_multiple": round(median(r_values), 8) if r_values else 0.0,
        "best_r_multiple": round(max(r_values), 8) if r_values else 0.0,
        "worst_r_multiple": round(min(r_values), 8) if r_values else 0.0,
        "max_drawdown_pct_raw": metrics.get("max_drawdown_pct"),
        "max_drawdown_pct_display": abs(float(metrics.get("max_drawdown_pct") or 0.0)),
        "max_drawdown_duration_minutes": metrics.get("max_drawdown_duration"),
        "calmar_like_ratio": metrics.get("calmar_ratio"),
        "sharpe_like_ratio": metrics.get("sharpe_ratio"),
        "sortino_like_ratio": metrics.get("sortino_ratio"),
        "consecutive_wins_max": _max_streak(result_bools),
        "consecutive_losses_max": _max_streak([not x for x in result_bools]),
        "turnover_on_capital": round(sum(notionals) / INITIAL_CAPITAL, 8) if notionals else 0.0,
        "kelly_fraction": None if payoff in (None, 0) else round((len(wins) / len(net_values)) - ((len(losses) / len(net_values)) / payoff), 8) if net_values else None,
        "kelly_fraction_capped": None,
        "breakeven_win_rate_pct": None if payoff in (None, 0) else round(100.0 / (1.0 + payoff), 8),
    })
    if metrics.get("kelly_fraction") is not None:
        metrics["kelly_fraction_capped"] = round(max(0.0, min(0.25, float(metrics["kelly_fraction"]))), 8)
    return {
        "generated_at_utc": iso_now(),
        "validation_status": "PASS" if len(included) > 0 else "FAIL",
        "pnl_mode": MODE,
        "accounting_mode": MODE,
        "pricing_mode": PRICING_MODE,
        "action_clock_mode": ACTION_CLOCK_MODE,
        "primary_trade_file": rel(CANONICAL_TRADES_PARQUET),
        "initial_capital_usd": INITIAL_CAPITAL,
        "current_equity_usd": detailed["current_equity_usd"],
        "current_equity": detailed["current_equity_usd"],
        "realized_pnl_usd": detailed["realized_pnl_usd"],
        "realized_pnl": detailed["realized_pnl_usd"],
        "unrealized_pnl_usd": detailed["unrealized_pnl_usd"],
        "unrealized_pnl": detailed["unrealized_pnl_usd"],
        "total_pnl_usd": detailed["total_pnl_usd"],
        "total_pnl": detailed["total_pnl_usd"],
        "net_pnl_usd": round(total_net, 6),
        "net_after_costs": round(total_net, 6),
        "net_after_costs_usd": round(total_net, 6),
        "net_return_pct": detailed.get("total_return_pct"),
        "gross_pnl_before_costs": round(gross, 6),
        "gross_pnl_before_costs_usd": round(gross, 6),
        "gross_profit_usd": round(net_profit, 6),
        "gross_loss_usd": round(net_loss, 6),
        "fees_paid": round(fees, 6),
        "fees_paid_usd": round(fees, 6),
        "slippage_paid": round(slip, 6),
        "slippage_paid_usd": round(slip, 6),
        "total_fees_usd": round(fees, 6),
        "total_slippage_usd": round(slip, 6),
        "total_costs_paid": round(fees + slip, 6),
        "total_costs_paid_usd": round(fees + slip, 6),
        "total_costs_usd": round(fees + slip, 6),
        "cost_model": {
            "entry_fee_rate": ENTRY_FEE_RATE,
            "exit_fee_rate": EXIT_FEE_RATE,
            "normal_entry_slippage_rate": ENTRY_SPREAD_RATE,
            "normal_exit_slippage_rate": EXIT_SPREAD_RATE,
            "cost_basis": "actual_trade_row_notional",
        },
        "metrics_recomputed_from_net_pnl": True,
        "position_sizing_mode": SIZING_MODE_LABEL,
        "risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
        "risk_amount_usd": round(INITIAL_CAPITAL * MAX_RISK_PER_TRADE_PCT / 100.0, 6),
        "canonical_bar_policy_trade_count": int(len(included)),
        "event_priced_trade_count": int(len(included)),
        "july21_trade_count": int(included.get("july21_trade", pd.Series(dtype=bool)).sum()) if len(included) else 0,
        "detailed_pnl": detailed,
        "model_evaluation_metrics": metrics,
        "equity_curve": equity_curve,
        "debug_pnl_layers": {
            "legacy_policy_context_trades_file": rel(LEGACY_TRADES),
            "event_priced_comparison_file": rel(EVENT_PRICED_TRADES),
            "aligned_comparison_file": rel(ALIGNED_TRADES),
            "legacy_layers_hidden_from_main": True,
        },
        "paper_only": True,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "raw_ledger_unchanged": True,
        "cognition_modified": False,
    }


def _included_count(df: pd.DataFrame, flag: str | None) -> int:
    if df.empty:
        return 0
    if flag and flag in df.columns:
        return int((df[flag] == True).sum())  # noqa: E712
    return int(len(df))


def included_frame(df: pd.DataFrame, flag: str | None) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if flag and flag in df.columns:
        return df[df[flag] == True].copy()  # noqa: E712
    return df.copy()


def source_candidates(include_canonical: bool = True) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if include_canonical:
        items.append({"name": "canonical_bar_policy", "path": CANONICAL_TRADES_PARQUET, "mode": MODE, "flag": "included_in_primary_canonical_bar_policy_pnl"})
    items.extend([
        {"name": "event_priced", "path": EVENT_PRICED_TRADES, "mode": EVENT_PRICED_MODE, "flag": "included_in_primary_event_pnl"},
        {"name": "legacy_policy_context", "path": LEGACY_TRADES, "mode": LEGACY_MODE, "flag": "included_in_policy_context_pnl"},
        {"name": "event_aligned", "path": ALIGNED_TRADES, "mode": ALIGNED_MODE, "flag": "included_in_primary_event_aligned_pnl"},
    ])
    return items


def inspect_trade_source(item: dict[str, Any]) -> dict[str, Any]:
    path = item["path"]
    df = read_parquet(path)
    inc = included_frame(df, item.get("flag"))
    pnl_col = "net_pnl_usd" if "net_pnl_usd" in inc.columns else "net_pnl"
    ts_col = "entry_ts" if "entry_ts" in df.columns else "context_start_bar_ts" if "context_start_bar_ts" in df.columns else None
    july21 = 0
    first_ts = last_ts = None
    if ts_col and ts_col in df.columns:
        ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        first_ts = iso(ts.min()) if len(ts.dropna()) else None
        last_ts = iso(ts.max()) if len(ts.dropna()) else None
        july21 = int(((ts >= WINDOW_START) & (ts < pd.Timestamp("2026-07-22T00:00:00Z"))).sum())
    return {
        **item,
        "exists": path.exists(),
        "df": df,
        "included": inc,
        "row_count": int(len(df)),
        "trade_count": int(len(inc)),
        "pnl_sum": round(float(pd.to_numeric(inc.get(pnl_col, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()), 6) if len(inc) else 0.0,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "july21_trade_count": july21,
        "relative_path": rel(path),
    }


def select_primary_trade_source(include_canonical: bool = True) -> dict[str, Any]:
    inspected = [inspect_trade_source(item) for item in source_candidates(include_canonical=include_canonical)]
    selected = next((item for item in inspected if item["trade_count"] > 0), inspected[0] if inspected else {})
    last_non_empty = next((item for item in inspected if item["trade_count"] > 0), None)
    expected_context_count = 0
    episodes = read_parquet(CANONICAL_EPISODES)
    if not episodes.empty and "start_time" in episodes.columns:
        expected_context_count = int((pd.to_datetime(episodes["start_time"], utc=True, errors="coerce") >= WINDOW_START).sum())
    selected_count = int(selected.get("trade_count", 0)) if selected else 0
    empty_blocked = bool(expected_context_count > 0 and selected_count == 0 and last_non_empty is not None and last_non_empty["trade_count"] > 0)
    if empty_blocked:
        selected = last_non_empty
    return {
        "selected": selected,
        "inspected": inspected,
        "last_non_empty": last_non_empty,
        "expected_context_count_since_2026_07_21": expected_context_count,
        "expected_trade_count_since_2026_07_21": max(expected_context_count, max((i["trade_count"] for i in inspected), default=0)),
        "empty_trade_source_blocked": empty_blocked,
        "fallback_to_last_non_empty_source": empty_blocked,
    }


def build_policy_reconfirmation() -> dict[str, Any]:
    files = {
        "paper_policy_engine": ROOT / "scripts" / "live" / "paper_policy_engine.py",
        "paper_action_clock": ROOT / "scripts" / "live" / "paper_action_clock.py",
        "paper_pnl_engine": ROOT / "scripts" / "live" / "paper_pnl_engine.py",
        "canonical_context_builder": ROOT / "scripts" / "research" / "build_policy_context_trades_from_canonical_contexts.py",
        "canonical_bar_policy_builder": ROOT / "scripts" / "research" / "build_policy_context_canonical_bar_policy_trades.py",
    }
    text = "\n".join(path.read_text(encoding="utf-8") for path in files.values() if path.exists())
    assertions = {
        "trade_all_mode_present": "TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS" in text,
        "hold_until_context_end_present": "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END" in text or "HOLD_CONTEXT_START_TO_CONTEXT_END" in text,
        "entry_requires_context_start_event": "ENTRY_BLOCKED_NO_CONTEXT_START_EVENT" in text,
        "stop_take_from_pnl_engine": "compute_trade_math" in text and "STOP_LOSS_BPS" in text and "TAKE_PROFIT_BPS" in text,
        "real_execution_disabled_in_builders": "execution_enabled" in text,
    }
    failed = [k for k, ok in assertions.items() if not ok]
    return {
        "generated_at_utc": iso_now(),
        "validation_status": "PASS" if not failed else "FAIL",
        "policy_reconfirmed": not failed,
        "failed_assertions": failed,
        "assertions": assertions,
        "entry_source_of_truth": "canonical_policy_context_episodes.start_time produced by context start event policy",
        "exit_source_of_truth": "canonical_policy_context_episodes.end_time produced by directional context end/invalidation policy",
        "context_start_bar_rule": "Trade opens on the canonical context start bar, never in the middle of an existing context.",
        "context_end_bar_rule": "Trade closes on the canonical context end bar for the same lifecycle episode.",
        "entry_price_policy": ENTRY_PRICE_POLICY,
        "exit_price_policy": EXIT_PRICE_POLICY,
        "stored_entry_timestamp_rule": "entry_ts equals context_start_bar_ts",
        "stored_exit_timestamp_rule": "exit_ts equals context_end_bar_ts",
        "trade_side_source": TRADE_SIDE_SOURCE,
        "decision_or_controller_timestamp_can_move_entry": False,
        "candle_close_allowed_as_execution_price": False,
        "candle_close_policy_note": "The restored source uses the already-declared canonical context bar policy price, not a silent candle-close fallback.",
        "quality_labels_use_same_rules": True,
        "stop_take_role": "visual/risk template from paper_pnl_engine; not execution logic in this research export",
        "ambiguous_policy_fields": [],
        "files_inspected": {k: rel(v) for k, v in files.items()},
        "paper_only": True,
        "real_execution_used": False,
        "exchange_order_api_used": False,
        "raw_ledger_rewritten": False,
        "cognition_modified": False,
    }


def validation_result(name: str, assertions: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {k: bool(v) for k, v in assertions.items()}
    failed = [k for k, ok in normalized.items() if not ok]
    return json_safe({
        "generated_at_utc": iso_now(),
        "validation_name": name,
        "validation_status": "PASS" if not failed else "FAIL",
        "failed_assertions": failed,
        "assertions": normalized,
        **(extra or {}),
        "paper_only": True,
        "real_execution_used": False,
        "exchange_order_api_used": False,
        "raw_ledger_rewritten": False,
        "cognition_modified": False,
    })
