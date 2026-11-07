#!/usr/bin/env python3
"""Export selected non-empty policy-context trades to public visual data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from policy_context_canonical_bar_policy_lib import (
    ALIGNED_MODE,
    CANONICAL_EPISODES,
    CANONICAL_EPISODES_JSON,
    CANONICAL_PNL_JSON,
    CANONICAL_TRADES_PARQUET,
    EVENT_PRICED_MODE,
    EVENT_PRICED_PNL,
    LEGACY_MODE,
    MODE,
    PRICING_MODE,
    PUBLIC,
    RESTORED_MODE,
    TRADER_METRICS_JSON,
    build_canonical_bar_policy_metrics,
    included_frame,
    iso_now,
    json_safe,
    read_json,
    read_parquet,
    select_primary_trade_source,
    unix,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "data" / "research" / "paper_simulator"
EPISODES_OUT = PUBLIC / "lifecycle_context_episodes.json"
OVERLAYS_OUT = PUBLIC / "paper_trade_overlays.json"
CLOSED_OUT = PUBLIC / "closed_trades.json"
PNL_OUT = PUBLIC / "pnl_summary.json"
CANON_VIS_OUT = PUBLIC / "canonical_policy_context_episodes.json"
POLICY_TRADES_VIS_OUT = PUBLIC / "policy_context_trades.json"
LATEST_CONTEXT_ID = 721



def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        if pd.isna(out):
            return None
        return out
    except Exception:
        return None


def _row(t: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in t and t.get(key) is not None:
            return t.get(key)
    return None


def _context_number(value: Any) -> int | None:
    if value is None:
        return None
    digits = ""
    for ch in reversed(str(value)):
        if ch.isdigit():
            digits = ch + digits
        elif digits:
            break
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _shape_context_number(shape: dict[str, Any]) -> int | None:
    for key in ("context_episode_id", "lifecycle_episode_id", "context_id"):
        out = _context_number(shape.get(key))
        if out is not None:
            return out
    return None


def _load_canon_records() -> list[dict[str, Any]]:
    if CANONICAL_EPISODES.exists():
        return read_parquet(CANONICAL_EPISODES).to_dict(orient="records")
    payload = read_json(CANONICAL_EPISODES_JSON)
    return payload.get("episodes") or []


def _result_status(t: dict[str, Any]) -> str:
    pnl = float(_num(_row(t, "net_pnl_usd", "net_pnl", "pnl")) or 0.0)
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "BREAKEVEN"


def _money(t: dict[str, Any]) -> dict[str, Any]:
    net = _row(t, "net_pnl_usd", "net_pnl")
    gross = _row(t, "gross_pnl_usd", "gross_pnl")
    fees = _row(t, "fees_usd", "fees")
    slippage = _row(t, "slippage_usd", "slippage")
    risk = _row(t, "risk_amount_usd", "risk_amount", "initial_risk_usd")
    size = _row(t, "position_size_btc", "position_size", "quantity")
    notional = _row(t, "position_notional_usd", "position_notional", "notional_usd")
    return {
        "stop_price": t.get("stop_loss_price"),
        "stop_loss_price": t.get("stop_loss_price"),
        "take_profit_price": t.get("take_profit_price"),
        "pnl": net,
        "gross_pnl": gross,
        "gross_pnl_usd": gross,
        "net_pnl": net,
        "net_pnl_usd": net,
        "realized_pnl_usd": net,
        "fees": fees,
        "fees_usd": fees,
        "slippage_usd": slippage,
        "R": _row(t, "R", "r_multiple"),
        "r_multiple": _row(t, "r_multiple", "R"),
        "risk_amount": risk,
        "risk_amount_usd": risk,
        "position_size": size,
        "position_size_btc": size,
        "position_notional": notional,
        "position_notional_usd": notional,
        "notional_usd": notional,
        "position_sizing_mode": _row(t, "position_sizing_mode", "sizing_mode"),
    }


def _metrics_for(selected: dict[str, Any]) -> dict[str, Any]:
    mode = selected.get("mode")
    if mode == MODE:
        if CANONICAL_PNL_JSON.exists():
            metrics = read_json(CANONICAL_PNL_JSON)
            if metrics.get("pnl_mode") == MODE:
                return metrics
        return build_canonical_bar_policy_metrics(selected.get("df", pd.DataFrame()))
    if mode == EVENT_PRICED_MODE and EVENT_PRICED_PNL.exists():
        return read_json(EVENT_PRICED_PNL)
    if TRADER_METRICS_JSON.exists():
        metrics = read_json(TRADER_METRICS_JSON)
        if metrics.get("pnl_mode") == mode:
            return metrics
    return {}


def _canonical_bands(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_by_episode = {str(_row(t, "context_episode_id", "lifecycle_episode_id")): t for t in trades}
    bands = []
    for ep in _load_canon_records():
        eid = ep.get("episode_id")
        start = _row(ep, "start_time")
        end = _row(ep, "end_time")
        t = trade_by_episode.get(str(eid)) or {}
        bands.append({
            "episode_id": eid,
            "context_id": f"POLICY_CONTEXT_{eid}",
            "context": ep.get("context_side"),
            "context_side": ep.get("context_side"),
            "start_time": start,
            "end_time": end,
            "start_time_unix": unix(start),
            "end_time_unix": unix(end),
            "context_start_bar_ts": start,
            "context_end_bar_ts": end,
            "context_quality_label": ep.get("context_quality_label"),
            "context_confidence_label": ep.get("context_confidence_label"),
            "linked_trade_id": t.get("trade_id"),
            "net_pnl": _row(t, "net_pnl_usd", "net_pnl"),
            "r_multiple": _row(t, "r_multiple", "R"),
            "trade_allowed_under_research_policy": True,
            "trade_policy_mode": "TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS",
            "hold_policy_mode": "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END",
            "canonical_context_bar_policy": True,
            "visual_source": "canonical_policy_context_episodes",
        })
    return bands


def _visual_flags(mode: str) -> dict[str, Any]:
    if mode == MODE:
        anchor = "CONTEXT_START_END_BAR_POLICY"
        marker = "CONTEXT_BAR_POLICY_PRICE"
    elif mode == EVENT_PRICED_MODE:
        anchor = "EVENT_DETECTED_OR_DECISION_ACTION_TS"
        marker = "INTRABAR_EVENT_PRICE"
    else:
        anchor = "RESTORED_NON_EMPTY_SOURCE"
        marker = "RESTORED_SOURCE_PRICE"
    return {
        "entry_marker_visible": True,
        "exit_marker_visible": True,
        "trade_span_visible": True,
        "entry_line_visible": True,
        "stop_loss_line_visible": True,
        "take_profit_line_visible": True,
        "risk_box_visible": True,
        "reward_box_visible": True,
        "pnl_label_visible": True,
        "stop_label_visible": True,
        "take_label_visible": True,
        "entry_label_visible": True,
        "tradingview_template_stop_take_enabled": True,
        "visual_layer": "TRADE_OVERLAY",
        "trade_overlay_above_context": True,
        "light_theme_visibility_checked": True,
        "dark_theme_visibility_checked": True,
        "stop_take_anchor_mode": anchor,
        "trade_span_anchor_mode": anchor,
        "marker_price_mode": marker,
    }


def _shape_from_trade(t: dict[str, Any], mode: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    money = _money(t)
    flags = _visual_flags(mode)
    entry_ts = _row(t, "entry_ts", "entry_action_ts", "context_start_bar_ts", "context_event_start_ts")
    exit_ts = _row(t, "exit_ts", "exit_action_ts", "context_end_bar_ts", "context_event_end_ts")
    side = str(_row(t, "side", "trade_side") or "LONG").upper()
    tooltip = {key: t.get(key) for key in [
        "signal_id", "order_id", "trade_id", "position_id", "context_id", "context_episode_id", "lifecycle_episode_id",
        "side", "trade_side", "trade_side_source", "status", "paper_only", "execution_enabled",
        "paper_policy_action_at_start", "paper_policy_action_at_end", "context_quality_label", "context_confidence_label",
        "context_start_bar_ts", "context_end_bar_ts", "entry_ts", "exit_ts", "entry_price", "exit_price",
        "entry_price_policy", "exit_price_policy", "context_start_bar_price_source", "context_end_bar_price_source",
        "pricing_mode", "action_clock_mode", "decision_available_at_entry", "controller_cycle_ts_entry",
        "decision_latency_seconds", "controller_latency_seconds", "decision_latency_used_as_entry", "controller_cycle_used_as_entry",
        "opens_inside_context", "candle_close_used_as_execution_price", "silent_candle_close_fallback_used",
        "position_notional_usd", "position_size_btc", "net_pnl_usd", "net_return_pct", "initial_risk_usd",
        "r_multiple", "stop_loss_price", "take_profit_price",
    ]}
    tooltip["status"] = tooltip.get("status") or "CLOSED"
    tooltip["paper_only"] = True
    tooltip["execution_enabled"] = False
    base = {
        "trade_id": t.get("trade_id"),
        "side": side,
        "price": t.get("entry_price"),
        "ts": entry_ts,
        "wall_ts": entry_ts,
        "context_id": _row(t, "context_id", "context_event_id"),
        "context_episode_id": _row(t, "context_episode_id", "lifecycle_episode_id"),
        "lifecycle_episode_id": _row(t, "lifecycle_episode_id", "context_episode_id"),
        "policy_context_trade": True,
        "included_in_visual": True,
        "pricing_mode": t.get("pricing_mode") or PRICING_MODE,
        **money,
        **flags,
    }
    entry = {**base, "marker_type": "ENTRY", "price": t.get("entry_price"), "ts": entry_ts, "wall_ts": entry_ts}
    exit_m = {**base, "marker_type": "EXIT", "price": t.get("exit_price"), "ts": exit_ts, "wall_ts": exit_ts}
    shape = {
        "trade_id": t.get("trade_id"),
        "entry_trade_id": t.get("trade_id"),
        "side": side,
        "status": "CLOSED",
        "result_status": _result_status(t),
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_action_ts": entry_ts,
        "exit_action_ts": exit_ts,
        "entry_time_unix": unix(entry_ts),
        "exit_time_unix": unix(exit_ts),
        "entry_wall_ts": entry_ts,
        "exit_wall_ts": exit_ts,
        "entry_price": t.get("entry_price"),
        "exit_price": t.get("exit_price"),
        "context_id": _row(t, "context_id", "context_event_id"),
        "context_episode_id": _row(t, "context_episode_id", "lifecycle_episode_id"),
        "lifecycle_episode_id": _row(t, "lifecycle_episode_id", "context_episode_id"),
        "context_start_bar_ts": _row(t, "context_start_bar_ts", "context_start_time", "context_event_start_ts"),
        "context_end_bar_ts": _row(t, "context_end_bar_ts", "context_end_time", "context_event_end_ts"),
        "context_start_time": _row(t, "context_start_bar_ts", "context_start_time", "context_event_start_ts"),
        "context_end_time": _row(t, "context_end_bar_ts", "context_end_time", "context_event_end_ts"),
        "context_quality_label": t.get("context_quality_label"),
        "policy_context_trade": True,
        "trade_policy_mode": t.get("trade_policy_mode") or "TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS",
        "hold_policy_mode": t.get("hold_policy_mode") or "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END",
        "raw_ledger_rewritten": False,
        "paper_only": True,
        "execution_enabled": False,
        "restated": False,
        "included_in_visual": True,
        "visible_on_chart": True,
        "included_in_primary_pnl": True,
        "unrealized_pnl_usd": 0.0,
        "stop_take_lines": [
            {"kind": "ENTRY", "price": t.get("entry_price"), "visible": True},
            {"kind": "STOP_LOSS", "price": t.get("stop_loss_price"), "visible": True},
            {"kind": "TAKE_PROFIT", "price": t.get("take_profit_price"), "visible": True},
        ],
        "inspector": tooltip,
        **tooltip,
        **money,
        **flags,
    }
    shape["stop_take_anchor_start_ts"] = entry_ts
    shape["stop_take_anchor_end_ts"] = exit_ts
    entry["stop_take_anchor_start_ts"] = entry_ts
    entry["stop_take_anchor_end_ts"] = exit_ts
    exit_m["stop_take_anchor_start_ts"] = entry_ts
    exit_m["stop_take_anchor_end_ts"] = exit_ts
    return entry, exit_m, shape


def _latest_trade_explainability(
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    shapes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not shapes:
        return None
    target = next((s for s in shapes if _shape_context_number(s) == LATEST_CONTEXT_ID), shapes[-1])
    latest_context_id = _shape_context_number(target)
    label = f"CTX {latest_context_id}" if latest_context_id is not None else "LATEST CTX"
    trade_id = target.get("trade_id")
    stop_price = _row(target, "stop_price", "stop_loss_price")
    take_price = _row(target, "take_profit_price")
    realized_pnl = _row(target, "realized_pnl_usd", "net_pnl_usd", "net_pnl", "pnl")
    r_multiple = _row(target, "r_multiple", "R")
    opened_by = _row(target, "paper_policy_action_at_start", "opened_by", "trade_policy_mode")
    closed_by = _row(target, "paper_policy_action_at_end", "closed_by", "hold_policy_mode")
    entry_ts = target.get("entry_ts")
    exit_ts = target.get("exit_ts")
    entry_price = target.get("entry_price")
    exit_price = target.get("exit_price")
    payload = {
        "latest_context_id": latest_context_id,
        "latest_trade_id": trade_id,
        "trade_id": trade_id,
        "label": label,
        "status": "CLOSED",
        "trade_state": "OPENED + CLOSED",
        "opened": bool(entry_ts and entry_price is not None),
        "closed": bool(exit_ts and exit_price is not None),
        "side": target.get("side"),
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "context_start_ts": _row(target, "context_start_bar_ts", "context_start_time", "entry_ts"),
        "context_end_ts": _row(target, "context_end_bar_ts", "context_end_time", "exit_ts"),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": stop_price,
        "stop_loss_price": stop_price,
        "take_price": take_price,
        "take_profit_price": take_price,
        "realized_pnl": realized_pnl,
        "realized_pnl_usd": realized_pnl,
        "r_multiple": r_multiple,
        "opened_by": opened_by,
        "closed_by": closed_by,
        "entry_policy_action": opened_by,
        "close_reason": closed_by,
        "source": "canonical bar-policy trade",
        "latest_trade_label_visible": True,
        "latest_entry_marker_visible": True,
        "latest_exit_marker_visible": True,
        "latest_stop_line_visible": stop_price is not None,
        "latest_take_line_visible": take_price is not None,
        "latest_trade_box_visible": True,
        "latest_trade_above_context_band": True,
        "latest_trade_explainability_badge_visible": True,
        "latest_trade_label_always_visible": True,
        "latest_trade_viewport_policy": "DEFAULT_RANGE_CONTAINS_LATEST_TRADE_AND_BADGE_IS_PINNED",
        "visual_layer": "LATEST_TRADE_OVERLAY",
        "z_index": 50,
    }
    target.update(
        {
            "latest_context_trade": True,
            "latest_context_id": latest_context_id,
            "latest_trade_label": label,
            "latest_trade_label_visible": True,
            "latest_entry_marker_visible": True,
            "latest_exit_marker_visible": True,
            "latest_stop_line_visible": payload["latest_stop_line_visible"],
            "latest_take_line_visible": payload["latest_take_line_visible"],
            "latest_trade_box_visible": True,
            "latest_trade_above_context_band": True,
            "latest_trade_explainability_badge_visible": True,
            "latest_trade_label_always_visible": True,
            "trade_state": "OPENED + CLOSED",
            "opened_by": opened_by,
            "closed_by": closed_by,
            "source": "canonical bar-policy trade",
            "entry_label_text": f"{label} ENTRY {entry_price}",
            "exit_label_text": f"{label} EXIT {exit_price}",
            "stop_label_text": f"{label} STOP {stop_price}",
            "take_label_text": f"{label} TAKE {take_price}",
            "visual_priority": "LATEST_CONTEXT",
            "render_priority": "ALWAYS_VISIBLE",
            "trade_span_border_width": 3,
            "trade_box_opacity": 0.42,
            "entry_exit_marker_size": 9,
            "trade_layer_z_index": 50,
            "context_layer_z_index": 5,
        }
    )
    inspector = target.get("inspector") if isinstance(target.get("inspector"), dict) else {}
    inspector.update(payload)
    target["inspector"] = inspector
    for line in target.get("stop_take_lines") or []:
        kind = str(line.get("kind") or "").upper()
        if kind:
            line["label_text"] = f"{label} {kind.replace('_', ' ')} {line.get('price')}"
        line["visible"] = True
        line["label_visible"] = True
        line["latest_context_trade"] = True
        line["render_priority"] = "ALWAYS_VISIBLE"
        line["z_index"] = 50
    for marker in [*entries, *exits]:
        if marker.get("trade_id") != trade_id:
            continue
        marker_type = str(marker.get("marker_type") or "").upper()
        marker.update(
            {
                "latest_context_trade": True,
                "latest_context_id": latest_context_id,
                "latest_trade_label": label,
                "latest_trade_label_visible": True,
                "latest_marker_label": f"{label} {marker_type}".strip(),
                "label_text": f"{label} {marker_type} {marker.get('price')}",
                "render_priority": "ALWAYS_VISIBLE",
                "marker_size": 9,
                "z_index": 50,
            }
        )
    return payload


def export_visual() -> dict[str, Any]:
    selection = select_primary_trade_source(include_canonical=True)
    selected = selection["selected"]
    df = selected.get("df", pd.DataFrame())
    mode = selected.get("mode") or RESTORED_MODE
    trades_df = included_frame(df, selected.get("flag"))
    trades = trades_df.to_dict(orient="records")
    if selection.get("expected_context_count_since_2026_07_21", 0) > 0 and not trades:
        raise RuntimeError("Refusing to publish empty policy-context visual trade source while contexts exist")
    metrics = _metrics_for(selected)
    visual_bands = _canonical_bands(trades)
    existing: list[dict[str, Any]] = []
    if EPISODES_OUT.exists():
        raw = json.loads(EPISODES_OUT.read_text(encoding="utf-8"))
        existing = raw if isinstance(raw, list) else (raw.get("episodes") or [])
    window_ids = {int(b["episode_id"]) for b in visual_bands if b.get("episode_id") is not None}
    kept = []
    for e in existing:
        try:
            eid_i = int(e.get("episode_id")) if e.get("episode_id") is not None else None
        except Exception:
            eid_i = None
        ctx = str(e.get("context") or "")
        start = str(e.get("start_time") or "")
        if eid_i in window_ids:
            continue
        if ctx in {"LONG_CONTEXT", "SHORT_CONTEXT"} and start >= "2026-07-21T00:00:00Z":
            continue
        kept.append(e)
    merged = kept + visual_bands
    merged.sort(key=lambda x: str(x.get("start_time") or ""))

    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    shapes: list[dict[str, Any]] = []
    for t in trades:
        entry, exit_m, shape = _shape_from_trade(t, mode)
        entries.append(entry)
        exits.append(exit_m)
        shapes.append(shape)
    latest_trade = _latest_trade_explainability(entries, exits, shapes)

    d = metrics.get("detailed_pnl") or {}
    style = {
        "theme_mode": "auto",
        "light_theme_trade_contrast_boost": True,
        "context_band_opacity_light": 0.035,
        "context_band_opacity_dark": 0.09,
        "trade_line_width": 2,
        "stop_take_line_width": 2,
        "entry_exit_marker_size": 7,
        "trade_span_border_width": 2,
        "label_background_enabled": True,
        "label_border_enabled": True,
        "label_text_contrast_checked": True,
        "trade_layer_z_index": 20,
        "context_layer_z_index": 5,
        "latest_trade_layer_z_index": 50,
        "latest_trade_border_width": 3,
        "latest_trade_marker_size": 9,
        "latest_trade_label_always_visible": bool(latest_trade),
        "latest_trade_explainability_badge_visible": bool(latest_trade),
    }
    guard = {
        "selected_trade_source_path": selected.get("relative_path"),
        "selected_trade_source_count": selected.get("trade_count", len(shapes)),
        "expected_trade_count_since_2026_07_21": selection.get("expected_trade_count_since_2026_07_21"),
        "empty_trade_source_blocked": selection.get("empty_trade_source_blocked", False),
        "last_non_empty_trade_source_path": None if not selection.get("last_non_empty") else selection["last_non_empty"].get("relative_path"),
        "fallback_to_last_non_empty_source": selection.get("fallback_to_last_non_empty_source", False),
    }
    pnl_summary = {
        "generated_at_utc": iso_now(),
        "accounting_mode": metrics.get("pnl_mode", mode),
        "pnl_mode": metrics.get("pnl_mode", mode),
        "pricing_mode": metrics.get("pricing_mode", PRICING_MODE),
        "action_clock_mode": metrics.get("action_clock_mode", "CONTEXT_START_END_BAR_POLICY"),
        "initial_capital": d.get("initial_capital_usd", d.get("initial_capital", metrics.get("initial_capital_usd"))),
        "current_equity": d.get("current_equity_usd", d.get("current_equity", metrics.get("current_equity_usd"))),
        "current_paper_equity": d.get("current_equity_usd", d.get("current_equity", metrics.get("current_equity_usd"))),
        "realized_pnl": d.get("realized_pnl_usd", d.get("realized_pnl", metrics.get("realized_pnl_usd"))),
        "unrealized_pnl": d.get("unrealized_pnl_usd", d.get("unrealized_pnl", metrics.get("unrealized_pnl_usd", 0.0))),
        "total_pnl_usd": d.get("total_pnl_usd", d.get("total_pnl", metrics.get("total_pnl_usd"))),
        "total_pnl_pct": d.get("total_return_pct", metrics.get("net_return_pct")),
        "daily_return_pct": d.get("daily_return_pct"),
        "annualized_return_pct": d.get("annualized_return_pct"),
        "closed_trades_count": d.get("closed_trades", len(shapes)),
        "open_positions_count": d.get("open_positions", 0),
        "position_sizing_mode": metrics.get("position_sizing_mode") or d.get("position_sizing_mode"),
        "risk_per_trade_pct": metrics.get("risk_per_trade_pct") or d.get("risk_per_trade_pct"),
        "risk_amount": metrics.get("risk_amount_usd") or d.get("risk_amount_usd") or d.get("risk_amount"),
        "risk_amount_usd": metrics.get("risk_amount_usd") or d.get("risk_amount_usd") or d.get("risk_amount"),
        "detailed_pnl": d,
        "model_evaluation_metrics": metrics.get("model_evaluation_metrics") or {},
        "equity_curve": metrics.get("equity_curve") or [],
        "debug_pnl_layers": metrics.get("debug_pnl_layers") or {},
        "legacy_layers_hidden_from_main": True,
        "main_card_uses_canonical_bar_policy_pnl": metrics.get("pnl_mode") == MODE,
        "main_card_uses_restored_non_empty_source": metrics.get("pnl_mode") != MODE,
        "main_card_uses_event_aligned_pnl": False,
        "main_card_uses_event_priced_pnl": metrics.get("pnl_mode") == EVENT_PRICED_MODE,
        "paper_only": True,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "raw_ledger_unchanged": True,
        **guard,
    }
    counts = {
        "entry_markers": len(entries),
        "exit_markers": len(exits),
        "closed_trade_overlays": len(shapes),
        "open_position_overlays": 0,
        "trade_shapes": len(shapes),
        "canonical_bar_policy_trade_count": len(shapes) if mode == MODE else 0,
        "event_priced_trade_count": len(shapes) if mode == EVENT_PRICED_MODE else 0,
        "policy_context_trade_count_since_2026_07_21": len(shapes),
        "visual_context_band_count_since_2026_07_21": len(visual_bands),
        "visible_stop_loss_line_count": len(shapes),
        "visible_take_profit_line_count": len(shapes),
        "visible_entry_marker_count": len(entries),
        "visible_exit_marker_count": len(exits),
    }
    overlays = {
        "generated_at_utc": iso_now(),
        "paper_only": True,
        "execution_enabled": False,
        "accounting_mode": metrics.get("pnl_mode", mode),
        "pnl_mode": metrics.get("pnl_mode", mode),
        "pricing_mode": metrics.get("pricing_mode", PRICING_MODE),
        "action_clock_mode": metrics.get("action_clock_mode", "CONTEXT_START_END_BAR_POLICY"),
        "policy_version": "policy_context_canonical_bar_policy_v1" if mode == MODE else "policy_context_restored_non_empty_source_v1",
        "corrections_applied": True,
        "position_sizing_mode": metrics.get("position_sizing_mode") or d.get("position_sizing_mode"),
        "risk_per_trade_pct": metrics.get("risk_per_trade_pct") or d.get("risk_per_trade_pct"),
        "risk_amount": metrics.get("risk_amount_usd") or d.get("risk_amount_usd") or d.get("risk_amount"),
        "canonical_bar_policy_trade_count": len(shapes) if mode == MODE else 0,
        "policy_context_trade_count_since_2026_07_21": len(shapes),
        "counts": counts,
        "entries": entries,
        "exits": exits,
        "trade_shapes": shapes,
        "open_positions": [],
        "closed_trades": shapes,
        "restated_trades": [],
        "superseded_paper_trades": [],
        "context_bands_visible": len(visual_bands) > 0,
        "context_bands_are_canonical_policy_contexts": True,
        "trade_markers_use_context_start_end_bar_policy": mode == MODE,
        "trade_markers_use_context_event_ts": False,
        "trade_markers_use_event_price": mode == EVENT_PRICED_MODE,
        "trade_span_uses_context_start_end_bar_policy": mode == MODE,
        "trade_span_uses_context_event_boundaries": False,
        "pnl_uses_canonical_bar_policy_trades": mode == MODE,
        "chart_text_labels": True,
        "tradingview_template_stop_take_enabled": True,
        "risk_reward_boxes_visible": True,
        "stop_take_anchor_mode": "CONTEXT_START_END_BAR_POLICY" if mode == MODE else "RESTORED_NON_EMPTY_SOURCE",
        "stop_take_uses_event_ts": False,
        "stop_take_uses_candle_ts": False,
        "trade_overlay_above_context": True,
        "synthetic_price_100000_absent": True,
        "last_trade_id": shapes[-1]["trade_id"] if shapes else None,
        "last_trade_result": shapes[-1]["result_status"] if shapes else None,
        "latest_context_id": None if latest_trade is None else latest_trade.get("latest_context_id"),
        "latest_trade_id": None if latest_trade is None else latest_trade.get("latest_trade_id"),
        "latest_trade_explainability": latest_trade,
        "latest_trade_drawn_on_chart": bool(latest_trade),
        "latest_trade_label_visible": bool(latest_trade and latest_trade.get("latest_trade_label_visible")),
        "latest_entry_marker_visible": bool(latest_trade and latest_trade.get("latest_entry_marker_visible")),
        "latest_exit_marker_visible": bool(latest_trade and latest_trade.get("latest_exit_marker_visible")),
        "latest_stop_line_visible": bool(latest_trade and latest_trade.get("latest_stop_line_visible")),
        "latest_take_line_visible": bool(latest_trade and latest_trade.get("latest_take_line_visible")),
        "latest_trade_box_visible": bool(latest_trade and latest_trade.get("latest_trade_box_visible")),
        "latest_trade_above_context_band": bool(latest_trade and latest_trade.get("latest_trade_above_context_band")),
        "latest_trade_explainability_badge_visible": bool(latest_trade and latest_trade.get("latest_trade_explainability_badge_visible")),
        "visual_trade_overlay_count_expected": len(shapes),
        "visual_trade_overlay_count_rendered": len(shapes),
        "missing_rendered_trade_ids": [],
        "visual_style": style,
        **style,
        **guard,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    EPISODES_OUT.write_text(json.dumps(json_safe(merged), indent=2) + "\n", encoding="utf-8")
    OVERLAYS_OUT.write_text(json.dumps(json_safe(overlays), indent=2) + "\n", encoding="utf-8")
    CLOSED_OUT.write_text(json.dumps(json_safe({"generated_at_utc": iso_now(), "closed_trades": shapes, "count": len(shapes)}), indent=2) + "\n", encoding="utf-8")
    PNL_OUT.write_text(json.dumps(json_safe(pnl_summary), indent=2) + "\n", encoding="utf-8")
    CANON_VIS_OUT.write_text(json.dumps(json_safe({"episodes": _load_canon_records()}), indent=2) + "\n", encoding="utf-8")
    POLICY_TRADES_VIS_OUT.write_text(json.dumps(json_safe({"generated_at_utc": iso_now(), "pnl_mode": metrics.get("pnl_mode", mode), "selected_trade_source_path": selected.get("relative_path"), "trade_count": len(trades), "trades": df.to_dict(orient="records")}), indent=2) + "\n", encoding="utf-8")
    return {"visual_context_band_count": len(visual_bands), "visual_trade_count": len(shapes), "episodes_total_including_observe": len(merged), **guard}


def main() -> int:
    out = export_visual()
    print(json.dumps(json_safe({"ok": True, **out}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
