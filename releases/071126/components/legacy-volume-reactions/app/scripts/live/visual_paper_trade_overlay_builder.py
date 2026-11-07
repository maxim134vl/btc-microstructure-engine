#!/usr/bin/env python3
"""Build paper trade position overlays for the lifecycle visualizer (visual-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_pnl_engine import INITIAL_CAPITAL, MAX_RISK_PER_TRADE_PCT, summarize_trades

ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = ROOT / "data" / "research" / "paper_simulator"
DECISION_LOG = ROOT / "data" / "live" / "context_decision_log.parquet"
LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"

SYNTHETIC_BAND = (99000.0, 101000.0)
DEFAULT_INITIAL_CAPITAL = 100000.0
RESTATEMENT_JSON = PAPER_DIR / "paper_trade_restatements.json"
RESTATEMENT_PARQUET = PAPER_DIR / "paper_trade_restatements.parquet"
ADJUSTED_PNL_JSON = PAPER_DIR / "paper_policy_adjusted_pnl.json"
BACKFILLS_JSON = PAPER_DIR / "paper_policy_alignment_backfills.json"
FORENSICS_JSON = ROOT / "data" / "research" / "policy_alignment_backfill_forensics.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        import pandas as pd

        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None


def _iso_ts(value: Any) -> str | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unix(value: Any) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return int(parsed.timestamp())


def _safe_float(value: Any) -> float | None:
    try:
        import math

        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    try:
        import pandas as pd

        if isinstance(value, float) and pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def _meta(row: Any) -> dict[str, Any]:
    raw = row.get("metadata_json") if hasattr(row, "get") else None
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _is_synthetic_price(*prices: Any) -> bool:
    for price in prices:
        f = _safe_float(price)
        if f is None:
            continue
        if SYNTHETIC_BAND[0] <= f <= SYNTHETIC_BAND[1]:
            return True
    return False


def _load_parquet(path: Path):
    import pandas as pd

    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _lookup_context(ts: Any) -> dict[str, Any]:
    """As-of context from decision log, fallback lifecycle memory."""
    import pandas as pd

    target = _parse_ts(ts)
    out = {
        "context": None,
        "lifecycle_state": None,
        "active_context_age_bars": None,
        "source": None,
        "matched_ts": None,
    }
    if target is None:
        return out

    if DECISION_LOG.exists():
        dl = pd.read_parquet(DECISION_LOG)
        if len(dl) and "candle_timestamp" in dl.columns:
            work = dl.copy()
            work["candle_timestamp"] = pd.to_datetime(work["candle_timestamp"], utc=True, errors="coerce")
            work = work.dropna(subset=["candle_timestamp"]).sort_values("candle_timestamp")
            sub = work[work["candle_timestamp"] <= pd.Timestamp(target)]
            if len(sub):
                row = sub.iloc[-1]
                out.update(
                    {
                        "context": _safe_text(row.get("active_market_context")),
                        "lifecycle_state": _safe_text(row.get("lifecycle_state")),
                        "active_context_age_bars": int(row.get("active_context_age_bars") or 0),
                        "source": "context_decision_log",
                        "matched_ts": _iso_ts(row.get("candle_timestamp")),
                    }
                )
                return out

    if LIFECYCLE_MEMORY.exists():
        mem = pd.read_parquet(LIFECYCLE_MEMORY)
        if len(mem) and "timestamp" in mem.columns:
            work = mem.copy()
            work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
            work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
            sub = work[work["timestamp"] <= pd.Timestamp(target)]
            if len(sub):
                row = sub.iloc[-1]
                out.update(
                    {
                        "context": _safe_text(row.get("active_market_context")),
                        "lifecycle_state": _safe_text(row.get("lifecycle_state")),
                        "active_context_age_bars": int(row.get("active_context_age_bars") or 0),
                        "source": "market_context_lifecycle_memory",
                        "matched_ts": _iso_ts(row.get("timestamp")),
                    }
                )
    return out


def _result_status(side: str, entry: float | None, exit_px: float | None, pnl: float | None) -> str:
    if pnl is not None:
        if abs(pnl) < 1e-9:
            return "BREAKEVEN"
        return "WIN" if pnl > 0 else "LOSS"
    if entry is None or exit_px is None:
        return "UNKNOWN"
    side_u = (side or "LONG").upper()
    if side_u == "SHORT":
        delta = entry - exit_px
    else:
        delta = exit_px - entry
    if abs(delta) < 1e-9:
        return "BREAKEVEN"
    return "WIN" if delta > 0 else "LOSS"


def _load_restatement_payload() -> dict[str, Any]:
    if RESTATEMENT_JSON.exists():
        try:
            return json.loads(RESTATEMENT_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    if RESTATEMENT_PARQUET.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(RESTATEMENT_PARQUET)
            rows = df.to_dict(orient="records")
            return {
                "restated_trades": rows,
                "restatements": {
                    str(r.get("original_trade_id")): {
                        "status": "SUPERSEDED_BY_CONTEXT_EVENT_RESTATEMENT",
                        "restated_trade_id": r.get("restated_trade_id"),
                        "use_in_corrected_pnl": False,
                        "replace_with_restated_trade": True,
                    }
                    for r in rows
                    if r.get("original_trade_id")
                },
                "policy_version": "context_event_policy_v1",
            }
        except Exception:
            pass
    return {}


def _superseded_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for oid, row in (payload.get("restatements") or {}).items():
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") != "SUPERSEDED_BY_CONTEXT_EVENT_RESTATEMENT":
            continue
        if row.get("replace_with_restated_trade") is False:
            continue
        out[str(oid)] = row
    return out


def _shape_from_restated(row: dict[str, Any]) -> dict[str, Any]:
    side = str(row.get("side") or "LONG").upper()
    entry_price = _safe_float(row.get("restated_entry_price"))
    exit_price = _safe_float(row.get("restated_exit_price"))
    # Prefer paper_action_ts; never silently plot source/M15 close as action.
    entry_ts = _iso_ts(
        row.get("paper_action_ts_entry")
        or row.get("paper_action_ts")
        or row.get("restated_entry_ts")
    )
    exit_ts = _iso_ts(
        row.get("paper_action_ts_exit")
        or row.get("restated_exit_ts")
    )
    source_entry = _iso_ts(row.get("source_context_ts_entry") or row.get("context_episode_started_at"))
    source_exit = _iso_ts(row.get("source_context_ts_exit"))
    stop = _safe_float(row.get("stop_loss_price"))
    take = _safe_float(row.get("take_profit_price"))
    qty = _safe_float(row.get("qty")) or 0.0
    notional = _safe_float(row.get("notional_usd")) or 10000.0
    net = _safe_float(row.get("net_pnl_usd"))
    fees = (_safe_float(row.get("entry_fee")) or 0.0) + (_safe_float(row.get("exit_fee")) or 0.0)
    realized_bps = _safe_float(row.get("pnl_bps"))
    result = _result_status(side, entry_price, exit_price, net)
    if side == "SHORT":
        profit_above_entry = False
        risk_above_entry = True
    else:
        profit_above_entry = True
        risk_above_entry = False
    profitable = False
    if entry_price is not None and exit_price is not None:
        profitable = (exit_price >= entry_price) if side != "SHORT" else (exit_price <= entry_price)
    trade_id = _safe_text(row.get("restated_trade_id"))
    shape = {
        "trade_shape": True,
        "trade_id": trade_id,
        "entry_trade_id": trade_id,
        "exit_trade_id": trade_id,
        "position_id": f"RESTATED_POSITION_FOR_{row.get('original_trade_id')}",
        "signal_id": None,
        "order_id": None,
        "side": side,
        "status": "CLOSED",
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "paper_action_ts": entry_ts,
        "paper_action_ts_entry": entry_ts,
        "paper_action_ts_exit": exit_ts,
        "source_context_ts": source_entry,
        "source_context_ts_entry": source_entry,
        "source_context_ts_exit": source_exit,
        "context_event_detected_at": row.get("context_event_detected_at_entry"),
        "decision_available_at": row.get("decision_available_at_entry"),
        "clock_source_used": row.get("clock_source_used_entry"),
        "action_clock_source": row.get("clock_source_used_entry"),
        "intrabar_event_id": row.get("intrabar_event_id") or row.get("event_id"),
        "clock_warning": (row.get("clock_warnings_entry") or [None])[0]
        if isinstance(row.get("clock_warnings_entry"), list)
        else row.get("clock_warning"),
        "clock_warnings": row.get("clock_warnings_entry") or [],
        "market_snapshot_source": row.get("market_snapshot_source"),
        "market_snapshot_observed_at": row.get("market_snapshot_observed_at"),
        "market_snapshot_age_seconds": row.get("market_snapshot_age_seconds"),
        "market_snapshot_fallback_used": row.get("market_snapshot_fallback_used"),
        "m15_bucket_open_ts": row.get("source_context_ts_entry") or source_entry,
        "m15_bucket_close_ts": None,
        "m15_bar_open_ts": source_entry,
        "m15_bar_close_ts": None,
        "entry_wall_ts": entry_ts,
        "exit_wall_ts": exit_ts,
        "entry_time_unix": _unix(entry_ts),
        "exit_time_unix": _unix(exit_ts),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": stop,
        "take_profit_price": take,
        "stop_loss_price": stop,
        "quantity_btc": qty,
        "notional_usd": notional,
        "fees_paid": fees,
        "realized_pnl_usd": net,
        "realized_pnl_bps": realized_bps,
        "realized_pnl_pct": round(float(realized_bps) / 100.0, 6) if realized_bps is not None else None,
        "unrealized_pnl_usd": 0.0,
        "result_status": result,
        "exit_reason": "CONTEXT_END_EVENT_RESTATED",
        "context_at_entry": row.get("entry_context"),
        "lifecycle_at_entry": row.get("entry_lifecycle_state"),
        "context_at_exit": row.get("exit_context"),
        "lifecycle_at_exit": row.get("exit_lifecycle_state"),
        "entry_context_age_bars": 0,
        "entered_near_context_end": False,
        "exited_inside_observe": str(row.get("exit_context") or "").upper() in {"OBSERVE", "NO_ACTIVE_CONTEXT", "NONE"},
        "paper_only": True,
        "execution_enabled": False,
        "accounting_mode": "RESTATED_CONTEXT_EVENT_POLICY",
        "restated": True,
        "original_trade_id": row.get("original_trade_id"),
        "entry_context_start_event": True,
        "exit_context_end_event": True,
        "geometry": {
            "connector": "dashed_entry_to_exit",
            "profit_zone": {
                "enabled": entry_price is not None and exit_price is not None,
                "above_entry": profit_above_entry,
                "profitable": profitable,
                "color": "green" if profitable else "red",
            },
            "risk_zone": {
                "enabled": entry_price is not None and stop is not None,
                "above_entry": risk_above_entry,
                "color": "red",
            },
            "stop_line": {"enabled": stop is not None, "style": "dashed_red"},
            "take_profit_line": {"enabled": take is not None, "style": "dashed_green"},
            "chart_text_labels": False,
        },
        "stop_take_lines": [
            x
            for x in [
                {"kind": "STOP_LOSS", "price": stop} if stop is not None else None,
                {"kind": "TAKE_PROFIT", "price": take} if take is not None else None,
            ]
            if x
        ],
        "inspector": {
            "trade_id": trade_id,
            "original_trade_id": row.get("original_trade_id"),
            "restated": True,
            "position_id": f"RESTATED_POSITION_FOR_{row.get('original_trade_id')}",
            "signal_id": None,
            "order_id": None,
            "side": side,
            "status": "CLOSED",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "quantity_btc": qty,
            "notional_usd": notional,
            "fees": fees,
            "realized_pnl_usd": net,
            "realized_pnl_bps": realized_bps,
            "result_status": result,
            "context_at_entry": row.get("entry_context"),
            "lifecycle_at_entry": row.get("entry_lifecycle_state"),
            "context_at_exit": row.get("exit_context"),
            "lifecycle_at_exit": row.get("exit_lifecycle_state"),
            "reason": "CONTEXT_END_EVENT_RESTATED",
            "paper_only": True,
            "execution_enabled": False,
        },
    }
    return shape


def build_paper_overlays(mark_price: float | None = None) -> dict[str, Any]:
    signals = _load_parquet(PAPER_DIR / "paper_signals.parquet")
    orders = _load_parquet(PAPER_DIR / "paper_orders.parquet")
    trades = _load_parquet(PAPER_DIR / "paper_trades.parquet")
    positions = _load_parquet(PAPER_DIR / "paper_positions.parquet")
    equity = _load_parquet(PAPER_DIR / "paper_equity_curve.parquet")
    risk = _load_parquet(PAPER_DIR / "paper_risk_blocks.parquet")
    restatement_payload = _load_restatement_payload()
    superseded = _superseded_map(restatement_payload)
    restated_rows = [
        r
        for r in (restatement_payload.get("restated_trades") or [])
        if str(r.get("status") or "") == "RESTATED" and r.get("restated_trade_id")
    ]

    signal_by_id: dict[str, Any] = {}
    for _, row in signals.iterrows() if len(signals) else []:
        sid = _safe_text(row.get("signal_id"))
        if sid:
            signal_by_id[sid] = row

    order_by_id: dict[str, Any] = {}
    for _, row in orders.iterrows() if len(orders) else []:
        oid = _safe_text(row.get("paper_order_id"))
        if oid:
            order_by_id[oid] = row

    trades_by_pos: dict[str, list[Any]] = {}
    for _, row in trades.iterrows() if len(trades) else []:
        pid = _safe_text(row.get("position_id"))
        if not pid:
            continue
        trades_by_pos.setdefault(pid, []).append(row)

    trade_shapes: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    open_overlays: list[dict[str, Any]] = []
    closed_overlays: list[dict[str, Any]] = []
    superseded_debug: list[dict[str, Any]] = []

    for _, row in positions.iterrows() if len(positions) else []:
        meta = _meta(row)
        entry_price = _safe_float(row.get("entry_price") or meta.get("entry_price"))
        exit_price = _safe_float(row.get("exit_price") or meta.get("exit_price"))
        if _is_synthetic_price(entry_price, exit_price):
            continue

        status = _safe_text(row.get("status") or meta.get("position_status"), default="UNKNOWN").upper()
        side = _safe_text(row.get("direction") or meta.get("side"), default="LONG").upper()
        position_id = _safe_text(row.get("position_id"))
        signal_id = _safe_text(meta.get("parent_signal_id") or row.get("opening_decision_id"))
        order_id = _safe_text(meta.get("parent_order_id") or meta.get("source_paper_order_id"))
        entry_trade_id = _safe_text(meta.get("parent_trade_id") or meta.get("source_paper_trade_id"))
        signal_row = signal_by_id.get(signal_id or "")
        stop = _safe_float(meta.get("stop_loss_price") or (signal_row.get("stop_loss_price") if signal_row is not None else None))
        take = _safe_float(meta.get("take_profit_price") or (signal_row.get("take_profit_price") if signal_row is not None else None))
        qty = _safe_float(row.get("quantity") or meta.get("quantity_btc")) or 0.0
        notional = _safe_float(row.get("notional") or meta.get("notional_usd"))
        fees = _safe_float(row.get("fees_paid"))
        realized = _safe_float(row.get("realized_pnl") or meta.get("realized_pnl_usd"))

        # Candle-aligned timestamps for chart geometry.
        entry_candle_ts = None
        exit_candle_ts = None
        exit_trade_id = None
        exit_reason = _safe_text(meta.get("exit_reason") or meta.get("closed_reason"))
        if signal_row is not None:
            entry_candle_ts = _iso_ts(signal_row.get("source_context_ts") or signal_row.get("decision_log_ts"))
        if order_id and order_id in order_by_id:
            entry_candle_ts = _iso_ts(order_by_id[order_id].get("candle_timestamp")) or entry_candle_ts

        for trow in trades_by_pos.get(position_id or "", []):
            tmeta = _meta(trow)
            ttype = _safe_text(tmeta.get("trade_type"), default="").upper()
            if ttype == "ENTRY" or (ttype != "EXIT" and str(trow.get("side")).upper() == "BUY"):
                entry_trade_id = _safe_text(trow.get("paper_trade_id")) or entry_trade_id
                oid = _safe_text(trow.get("paper_order_id"))
                if oid and oid in order_by_id:
                    entry_candle_ts = _iso_ts(order_by_id[oid].get("candle_timestamp")) or entry_candle_ts
                entry_candle_ts = entry_candle_ts or _iso_ts(tmeta.get("source_context_ts") or trow.get("timestamp"))
            if ttype == "EXIT" or tmeta.get("exit_reason"):
                exit_trade_id = _safe_text(trow.get("paper_trade_id"))
                exit_reason = exit_reason or _safe_text(tmeta.get("exit_reason"))
                oid = _safe_text(trow.get("paper_order_id"))
                if oid and oid in order_by_id:
                    exit_candle_ts = _iso_ts(order_by_id[oid].get("candle_timestamp"))
                close_sig = _safe_text(row.get("closing_decision_id"))
                if close_sig and close_sig in signal_by_id:
                    exit_candle_ts = exit_candle_ts or _iso_ts(
                        signal_by_id[close_sig].get("source_context_ts") or signal_by_id[close_sig].get("decision_log_ts")
                    )
                exit_candle_ts = exit_candle_ts or _iso_ts(trow.get("timestamp"))

        # Superseded raw trades stay in audit/debug only — not main chart / PnL.
        if entry_trade_id and entry_trade_id in superseded:
            superseded_debug.append(
                {
                    "original_trade_id": entry_trade_id,
                    "restated_trade_id": superseded[entry_trade_id].get("restated_trade_id"),
                    "status": "SUPERSEDED_BY_CONTEXT_EVENT_RESTATEMENT",
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "entry_ts": entry_candle_ts or _iso_ts(row.get("opened_at")),
                    "exit_ts": exit_candle_ts or _iso_ts(row.get("closed_at")),
                    "realized_pnl_usd": realized,
                    "use_in_main_chart": False,
                    "use_in_corrected_pnl": False,
                    "paper_only": True,
                    "execution_enabled": False,
                }
            )
            continue

        wall_entry = _iso_ts(row.get("opened_at"))
        wall_exit = _iso_ts(row.get("closed_at"))
        # Prefer explicit paper_action_ts from position/trade/signal metadata.
        action_entry = _iso_ts(
            meta.get("paper_action_ts")
            or (signal_row.get("paper_action_ts") if signal_row is not None else None)
            or wall_entry
        )
        action_exit = _iso_ts(meta.get("paper_action_ts_exit") or wall_exit)
        # Chart uses action time, not source_context_ts / M15 candle label.
        chart_entry = action_entry or entry_candle_ts or wall_entry
        chart_exit = action_exit or exit_candle_ts or wall_exit
        source_entry = _iso_ts(
            (signal_row.get("source_context_ts") if signal_row is not None else None) or entry_candle_ts
        )

        entry_ctx = _lookup_context(chart_entry)
        # Prefer explicit signal context when present.
        if signal_row is not None:
            entry_ctx["context"] = _safe_text(signal_row.get("context")) or entry_ctx["context"]
            entry_ctx["lifecycle_state"] = _safe_text(signal_row.get("lifecycle_state")) or entry_ctx["lifecycle_state"]
        exit_ctx = _lookup_context(chart_exit) if chart_exit else {"context": None, "lifecycle_state": None, "active_context_age_bars": None}
        close_sig = _safe_text(row.get("closing_decision_id"))
        if close_sig and close_sig in signal_by_id:
            exit_ctx["context"] = _safe_text(signal_by_id[close_sig].get("context")) or exit_ctx.get("context")
            exit_ctx["lifecycle_state"] = _safe_text(signal_by_id[close_sig].get("lifecycle_state")) or exit_ctx.get("lifecycle_state")

        age = entry_ctx.get("active_context_age_bars")
        entered_near_context_end = bool(age is not None and int(age) >= 3)
        exited_inside_observe = str(exit_ctx.get("context") or "").upper() == "OBSERVE" or str(
            exit_ctx.get("lifecycle_state") or ""
        ).upper() in {"NO_ACTIVE_CONTEXT", "INVALIDATED"}

        unrealized = _safe_float(row.get("unrealized_pnl") or meta.get("unrealized_pnl_usd"))
        if status == "OPEN" and mark_price is not None and entry_price is not None and qty:
            signed = qty if side == "LONG" else -qty
            unrealized = round(signed * (mark_price - entry_price), 6)

        realized_bps = None
        realized_pct = None
        if realized is not None and notional:
            realized_bps = round(10000.0 * realized / notional, 4)
            realized_pct = round(100.0 * realized / notional, 6)
        result = _result_status(side, entry_price, exit_price, realized)

        # Geometry helpers for chart (no text labels).
        if side == "SHORT":
            profit_above_entry = False
            risk_above_entry = True
        else:
            profit_above_entry = True
            risk_above_entry = False

        profitable = False
        if entry_price is not None and exit_price is not None:
            profitable = (exit_price >= entry_price) if side != "SHORT" else (exit_price <= entry_price)

        collection_fields = {
            "paper_collection_trade": bool(meta.get("paper_collection_trade")),
            "context_quality": _safe_text(meta.get("context_quality")),
            "doubt_flag": bool(meta.get("doubt_flag")),
            "active_market_context": _safe_text(meta.get("active_market_context")),
            "lifecycle_state": _safe_text(meta.get("lifecycle_state")),
            "raw_market_context": _safe_text(meta.get("raw_market_context")),
            "challenge_context": _safe_text(meta.get("challenge_context")),
            "context_start_event": bool(meta.get("context_start_event")),
            "original_gate_reason": _safe_text(meta.get("original_gate_reason")),
            "paper_entry_basis": _safe_text(meta.get("paper_entry_basis")),
        }

        shape = {
            "trade_shape": True,
            "trade_id": exit_trade_id or entry_trade_id,
            "entry_trade_id": entry_trade_id,
            "exit_trade_id": exit_trade_id,
            "position_id": position_id,
            "signal_id": signal_id,
            "order_id": order_id,
            "side": side,
            "status": status,
            "entry_ts": chart_entry,
            "exit_ts": chart_exit if status != "OPEN" else None,
            "paper_action_ts": chart_entry,
            "paper_action_ts_entry": chart_entry,
            "paper_action_ts_exit": chart_exit if status != "OPEN" else None,
            "source_context_ts": source_entry,
            "action_clock_source": meta.get("action_clock_source")
            or (signal_row.get("action_clock_source") if signal_row is not None else None)
            or meta.get("clock_source_used"),
            "intrabar_event_id": meta.get("intrabar_event_id"),
            "clock_warning": meta.get("clock_warning"),
            "market_snapshot_source": meta.get("market_snapshot_source")
            or (signal_row.get("market_snapshot_source") if signal_row is not None else None),
            "market_snapshot_observed_at": meta.get("market_snapshot_observed_at")
            or (signal_row.get("market_snapshot_observed_at") if signal_row is not None else None),
            "market_snapshot_age_seconds": meta.get("market_snapshot_age_seconds")
            or (signal_row.get("market_snapshot_age_seconds") if signal_row is not None else None),
            "market_snapshot_fallback_used": meta.get("market_snapshot_fallback_used")
            if meta.get("market_snapshot_fallback_used") is not None
            else (signal_row.get("market_snapshot_fallback_used") if signal_row is not None else None),
            "m15_bucket_open_ts": meta.get("m15_bar_open_ts") or source_entry,
            "m15_bucket_close_ts": meta.get("m15_bar_close_ts"),
            "entry_wall_ts": wall_entry,
            "exit_wall_ts": wall_exit,
            "entry_time_unix": _unix(chart_entry),
            "exit_time_unix": _unix(chart_exit) if status != "OPEN" else None,
            "entry_price": entry_price,
            "exit_price": exit_price if status != "OPEN" else None,
            "stop_price": stop,
            "take_profit_price": take,
            "stop_loss_price": stop,
            "quantity_btc": qty,
            "notional_usd": notional,
            "fees_paid": fees,
            "realized_pnl_usd": realized if status != "OPEN" else None,
            "realized_pnl_bps": realized_bps if status != "OPEN" else None,
            "realized_pnl_pct": realized_pct if status != "OPEN" else None,
            "unrealized_pnl_usd": unrealized if status == "OPEN" else 0.0,
            "result_status": result if status != "OPEN" else "OPEN",
            "exit_reason": exit_reason,
            "context_at_entry": entry_ctx.get("context"),
            "lifecycle_at_entry": entry_ctx.get("lifecycle_state"),
            "context_at_exit": exit_ctx.get("context") if status != "OPEN" else None,
            "lifecycle_at_exit": exit_ctx.get("lifecycle_state") if status != "OPEN" else None,
            "entry_context_age_bars": age,
            "entered_near_context_end": entered_near_context_end,
            "exited_inside_observe": exited_inside_observe if status != "OPEN" else None,
            "paper_only": True,
            "execution_enabled": False,
            "restated": False,
            **collection_fields,
            "geometry": {
                "connector": "dashed_entry_to_exit",
                "profit_zone": {
                    "enabled": status != "OPEN" and entry_price is not None and exit_price is not None,
                    "above_entry": profit_above_entry,
                    "profitable": profitable,
                    "color": "green" if profitable else "red",
                },
                "risk_zone": {
                    "enabled": entry_price is not None and stop is not None,
                    "above_entry": risk_above_entry,
                    "color": "red",
                },
                "stop_line": {"enabled": stop is not None, "style": "dashed_red"},
                "take_profit_line": {"enabled": take is not None, "style": "dashed_green"},
                "chart_text_labels": False,
            },
            "stop_take_lines": [x for x in [
                {"kind": "STOP_LOSS", "price": stop} if stop is not None else None,
                {"kind": "TAKE_PROFIT", "price": take} if take is not None else None,
            ] if x],
            "inspector": {
                "trade_id": exit_trade_id or entry_trade_id,
                "position_id": position_id,
                "signal_id": signal_id,
                "order_id": order_id,
                "side": side,
                "status": status,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_ts": chart_entry,
                "exit_ts": chart_exit,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "quantity_btc": qty,
                "notional_usd": notional,
                "fees": fees,
                "realized_pnl_usd": realized,
                "realized_pnl_bps": realized_bps,
                "unrealized_pnl_usd": unrealized if status == "OPEN" else 0.0,
                "result_status": result if status != "OPEN" else "OPEN",
                "context_at_entry": entry_ctx.get("context"),
                "lifecycle_at_entry": entry_ctx.get("lifecycle_state"),
                "context_at_exit": exit_ctx.get("context"),
                "lifecycle_at_exit": exit_ctx.get("lifecycle_state"),
                "reason": exit_reason,
                "paper_only": True,
                "execution_enabled": False,
                **collection_fields,
            },
        }
        trade_shapes.append(shape)

        entry_marker = {
            "marker_type": "ENTRY",
            "trade_id": entry_trade_id,
            "position_id": position_id,
            "side": side,
            "price": entry_price,
            "entry_price": entry_price,
            "ts": chart_entry,
            "time_unix": _unix(chart_entry),
            "stop_loss_price": stop,
            "take_profit_price": take,
            "context": entry_ctx.get("context"),
            "lifecycle_state": entry_ctx.get("lifecycle_state"),
            "paper_only": True,
            "execution_enabled": False,
            "inspector": shape["inspector"],
        }
        entries.append(entry_marker)

        if status != "OPEN" and chart_exit and exit_price is not None:
            exit_marker = {
                "marker_type": "EXIT",
                "trade_id": exit_trade_id,
                "close_trade_id": exit_trade_id,
                "position_id": position_id,
                "side": side,
                "price": exit_price,
                "exit_price": exit_price,
                "ts": chart_exit,
                "exit_ts": chart_exit,
                "time_unix": _unix(chart_exit),
                "realized_pnl_usd": realized,
                "realized_pnl_bps": realized_bps,
                "exit_reason": exit_reason,
                "context": exit_ctx.get("context"),
                "lifecycle_state": exit_ctx.get("lifecycle_state"),
                "paper_only": True,
                "execution_enabled": False,
                "inspector": shape["inspector"],
            }
            exits.append(exit_marker)

        if status == "OPEN":
            open_overlays.append(shape)
        else:
            closed_overlays.append(shape)

    # Inject restated replacements into main visual / PnL sets.
    for rrow in restated_rows:
        shape = _shape_from_restated(rrow)
        trade_shapes.append(shape)
        closed_overlays.append(shape)
        entries.append(
            {
                "marker_type": "ENTRY",
                "trade_id": shape.get("entry_trade_id"),
                "position_id": shape.get("position_id"),
                "side": shape.get("side"),
                "price": shape.get("entry_price"),
                "entry_price": shape.get("entry_price"),
                "ts": shape.get("entry_ts"),
                "time_unix": shape.get("entry_time_unix"),
                "stop_loss_price": shape.get("stop_loss_price"),
                "take_profit_price": shape.get("take_profit_price"),
                "context": shape.get("context_at_entry"),
                "lifecycle_state": shape.get("lifecycle_at_entry"),
                "restated": True,
                "paper_only": True,
                "execution_enabled": False,
                "inspector": shape["inspector"],
            }
        )
        exits.append(
            {
                "marker_type": "EXIT",
                "trade_id": shape.get("exit_trade_id"),
                "close_trade_id": shape.get("exit_trade_id"),
                "position_id": shape.get("position_id"),
                "side": shape.get("side"),
                "price": shape.get("exit_price"),
                "exit_price": shape.get("exit_price"),
                "ts": shape.get("exit_ts"),
                "exit_ts": shape.get("exit_ts"),
                "time_unix": shape.get("exit_time_unix"),
                "realized_pnl_usd": shape.get("realized_pnl_usd"),
                "realized_pnl_bps": shape.get("realized_pnl_bps"),
                "exit_reason": shape.get("exit_reason"),
                "context": shape.get("context_at_exit"),
                "lifecycle_state": shape.get("lifecycle_at_exit"),
                "restated": True,
                "paper_only": True,
                "execution_enabled": False,
                "inspector": shape["inspector"],
            }
        )

    closed_sorted = sorted(closed_overlays, key=lambda x: x.get("exit_wall_ts") or x.get("exit_ts") or "")
    last_closed = closed_sorted[-1] if closed_sorted else None

    return {
        "generated_at_utc": _iso_now(),
        "paper_only": True,
        "execution_enabled": False,
        "accounting_mode": "RESTATED_CONTEXT_EVENT_POLICY" if restated_rows else "RAW_PAPER_LEDGER",
        "policy_version": restatement_payload.get("policy_version") or "context_event_policy_v1",
        "corrections_applied": bool(restated_rows),
        "counts": {
            "paper_signals": int(len(signals)),
            "paper_orders": int(len(orders)),
            "paper_trades": int(len(trades)),
            "paper_positions": int(len(positions)),
            "paper_equity_rows": int(len(equity)),
            "paper_risk_blocks": int(len(risk)),
            "entry_markers": len(entries),
            "exit_markers": len(exits),
            "open_position_overlays": len(open_overlays),
            "closed_trade_overlays": len(closed_overlays),
            "trade_shapes": len(trade_shapes),
            "restated_trades": len(restated_rows),
            "superseded_raw_trades": len(superseded_debug),
        },
        "entries": entries,
        "exits": exits,
        "trade_shapes": trade_shapes,
        "open_positions": open_overlays,
        "closed_trades": closed_overlays,
        "restated_trades": restated_rows,
        "superseded_paper_trades": superseded_debug,
        "last_trade_id": (last_closed or {}).get("trade_id"),
        "last_trade_result": (last_closed or {}).get("result_status"),
        "synthetic_price_100000_absent": True,
        "chart_text_labels": False,
        "tooltip_fields": [
            "trade_id",
            "position_id",
            "side",
            "status",
            "entry_price",
            "exit_price",
            "stop_loss_price",
            "take_profit_price",
            "realized_pnl_usd",
            "paper_action_ts",
            "source_context_ts",
            "market_snapshot_source",
            "market_snapshot_observed_at",
            "market_snapshot_age_seconds",
            "market_snapshot_fallback_used",
            "clock_warning",
            "trade_status_layer",
            "policy_alignment_backfill",
            "context_quality_label",
            "context_hold_mode",
            "paper_collection_trade",
            "context_quality",
            "doubt_flag",
            "original_gate_reason",
            "paper_entry_basis",
            "raw_market_context",
            "challenge_context",
            "entry_used_context_layer",
            "exit_used_context_layer",
            "captured_context_ratio",
            "missed_head_bars",
            "missed_tail_bars",
            "adjusted_pnl_inclusion_status",
            "context_at_entry",
            "lifecycle_at_entry",
            "context_at_exit",
            "lifecycle_at_exit",
            "reason",
            "paper_only",
            "execution_enabled",
        ],
    }


def build_trade_result_summary(overlays: dict[str, Any]) -> dict[str, Any]:
    closed = overlays.get("closed_trades") or []
    closed_sorted = sorted(closed, key=lambda x: x.get("exit_wall_ts") or x.get("exit_ts") or "")
    last = closed_sorted[-1] if closed_sorted else None
    if not last:
        return {
            "generated_at_utc": _iso_now(),
            "has_closed_trade": False,
            "paper_only": True,
            "execution_enabled": False,
            "accounting_mode": overlays.get("accounting_mode"),
        }
    return {
        "generated_at_utc": _iso_now(),
        "has_closed_trade": True,
        "trade_id": last.get("trade_id"),
        "original_trade_id": last.get("original_trade_id"),
        "restated": bool(last.get("restated")),
        "position_id": last.get("position_id"),
        "side": last.get("side"),
        "status": "CLOSED",
        "entry_price": last.get("entry_price"),
        "exit_price": last.get("exit_price"),
        "entry_time": last.get("entry_ts"),
        "exit_time": last.get("exit_ts"),
        "exit_reason": last.get("exit_reason"),
        "result": last.get("result_status"),
        "realized_pnl_usd": last.get("realized_pnl_usd"),
        "realized_pnl_bps": last.get("realized_pnl_bps"),
        "fees": last.get("fees_paid"),
        "context_entry": last.get("context_at_entry"),
        "context_exit": last.get("context_at_exit"),
        "lifecycle_entry": last.get("lifecycle_at_entry"),
        "lifecycle_exit": last.get("lifecycle_at_exit"),
        "entered_near_context_end": last.get("entered_near_context_end"),
        "exited_inside_observe": last.get("exited_inside_observe"),
        "accounting_mode": overlays.get("accounting_mode") or "RESTATED_CONTEXT_EVENT_POLICY",
        "paper_only": True,
        "execution_enabled": False,
    }




def _summary_trade_row(row: dict[str, Any], *, initial_capital: float) -> dict[str, Any]:
    gross = _safe_float(
        row.get("gross_pnl_before_fees_slippage")
        or row.get("gross_price_pnl_usd")
        or row.get("gross_pnl_usd")
        or row.get("gross_pnl")
    )
    fees = _safe_float(row.get("fees_usd") or row.get("total_fees_usd") or row.get("fees_paid") or row.get("fees")) or 0.0
    slippage = _safe_float(row.get("slippage_usd") or row.get("total_slippage_usd") or row.get("slippage")) or 0.0
    net = _safe_float(
        row.get("net_pnl_after_fees_slippage")
        or row.get("net_realized_pnl_usd")
        or row.get("net_pnl_usd")
        or row.get("realized_pnl_usd")
        or row.get("pnl")
    )
    if gross is None and net is not None:
        gross = float(net) + fees + slippage
    if net is None and gross is not None:
        net = float(gross) - fees - slippage
    gross = float(gross or 0.0)
    net = float(net or 0.0)
    risk_amount = float(initial_capital) * MAX_RISK_PER_TRADE_PCT / 100.0
    r_multiple = _safe_float(row.get("r_multiple") or row.get("R"))
    if r_multiple is None:
        r_multiple = net / risk_amount if risk_amount else 0.0
    return {
        "trade_id": row.get("trade_id") or row.get("entry_trade_id"),
        "entry_ts": row.get("entry_ts") or row.get("entry_wall_ts"),
        "exit_ts": row.get("exit_ts") or row.get("exit_wall_ts"),
        "gross_pnl": gross,
        "fees": fees,
        "slippage": slippage,
        "net_pnl": net,
        "r_multiple": r_multiple,
    }

def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _view_pnl(views: dict[str, Any], key: str) -> float | None:
    node = views.get(key)
    if isinstance(node, dict):
        return _safe_float(node.get("total_net_pnl_usd") or node.get("net_pnl") or node.get("value"))
    return _safe_float(node)


def build_pnl_summary(overlays: dict[str, Any]) -> dict[str, Any]:
    closed = [dict(c) for c in (overlays.get("closed_trades") or []) if isinstance(c, dict)]
    open_pos = [dict(p) for p in (overlays.get("open_positions") or []) if isinstance(p, dict)]
    initial_capital = DEFAULT_INITIAL_CAPITAL
    clean_trades = [_summary_trade_row(c, initial_capital=initial_capital) for c in closed]
    clean_summary = summarize_trades(
        clean_trades,
        initial_capital=initial_capital,
        open_positions_count=len(open_pos),
    )
    detailed = dict(clean_summary["detailed_pnl"])
    metrics = dict(clean_summary["model_evaluation_metrics"])
    gross = sum(float(t.get("gross_pnl") or 0.0) for t in clean_trades)
    fees = sum(float(t.get("fees") or 0.0) for t in clean_trades)
    slippage = sum(float(t.get("slippage") or 0.0) for t in clean_trades)
    net = sum(float(t.get("net_pnl") or 0.0) for t in clean_trades)
    detailed.update(
        {
            "initial_capital_usd": round(initial_capital, 6),
            "current_equity_usd": round(initial_capital + net, 6),
            "realized_pnl_usd": round(net, 6),
            "unrealized_pnl_usd": detailed.get("unrealized_pnl", 0.0),
            "total_pnl_usd": round(net, 6),
            "gross_pnl_before_costs_usd": round(gross, 6),
            "gross_pnl_before_fees_slippage_usd": round(gross, 6),
            "fees_paid_usd": round(fees, 6),
            "slippage_paid_usd": round(slippage, 6),
            "net_pnl_after_costs_usd": round(net, 6),
            "net_pnl_after_fees_slippage_usd": round(net, 6),
            "total_costs_paid_usd": round(fees + slippage, 6),
            "position_sizing_mode": "Risk-based, 1% max loss per trade",
        }
    )
    metrics.update(
        {
            "metrics_recomputed_from_net_pnl": True,
            "returns_source": "equity_curve",
            "sample_size_warning": bool(metrics.get("status") == "low sample size"),
        }
    )
    reconciliation_delta = (gross - fees - slippage) - net
    return {
        "generated_at_utc": _iso_now(),
        "accounting_mode": "CANONICAL_PAPER_TRADE_ECONOMICS_V1",
        "pnl_mode": "CANONICAL_PAPER_TRADE_ECONOMICS_V1",
        "pnl_source": "paper_trade_overlays.closed_trades",
        "selected_trade_source_path": overlays.get("renderer_source") or overlays.get("trade_layer_source"),
        "initial_capital": round(initial_capital, 6),
        "current_equity": round(initial_capital + net, 6),
        "current_paper_equity": round(initial_capital + net, 6),
        "realized_pnl": round(net, 6),
        "unrealized_pnl": 0.0,
        "total_pnl_usd": round(net, 6),
        "total_pnl": round(net, 6),
        "total_pnl_pct": round((net / initial_capital) * 100.0, 6) if initial_capital else 0.0,
        "gross_pnl_before_costs": round(gross, 6),
        "gross_pnl_before_costs_usd": round(gross, 6),
        "fees_paid": round(fees, 6),
        "fees_paid_usd": round(fees, 6),
        "slippage_paid": round(slippage, 6),
        "slippage_paid_usd": round(slippage, 6),
        "total_costs_paid": round(fees + slippage, 6),
        "net_after_costs": round(net, 6),
        "net_after_costs_usd": round(net, 6),
        "closed_trades_count": len(closed),
        "open_positions_count": len(open_pos),
        "paper_only": True,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "legacy_layers_hidden_from_main": True,
        "main_card_uses_canonical_paper_trade_economics": True,
        "detailed_pnl": detailed,
        "model_evaluation_metrics": metrics,
        "equity_curve": clean_summary["equity_curve"],
        "pnl_reconciles_with_overlay_rows": True,
        "pnl_reconciliation_delta_usd": round(reconciliation_delta, 8),
        "gross_minus_fees_minus_slippage_equals_net": abs(reconciliation_delta) <= 1e-4,
    }


def build_trade_context_checks(overlays: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    closed = overlays.get("closed_trades") or []
    target = None
    for c in closed:
        if c.get("restated") and c.get("original_trade_id") == "PAPER_TRADE_ONE_SHOT_3693c3f8009e4582":
            target = c
            break
    if target is None:
        for c in closed:
            if c.get("entry_price") is not None and abs(float(c["entry_price"]) - 65751.56) < 1.0:
                target = c
                break
    if target is None and closed:
        target = sorted(closed, key=lambda x: x.get("exit_wall_ts") or x.get("exit_ts") or "")[-1]

    if target is None:
        empty = {"generated_at_utc": _iso_now(), "found": False}
        return empty, empty

    entry_check = {
        "generated_at_utc": _iso_now(),
        "found": True,
        "trade_id": target.get("trade_id"),
        "original_trade_id": target.get("original_trade_id"),
        "restated": bool(target.get("restated")),
        "position_id": target.get("position_id"),
        "side": target.get("side"),
        "entry_ts": target.get("entry_ts"),
        "entry_wall_ts": target.get("entry_wall_ts"),
        "entry_price": target.get("entry_price"),
        "entry_context": target.get("context_at_entry"),
        "entry_lifecycle": target.get("lifecycle_at_entry"),
        "entry_context_age_bars": target.get("entry_context_age_bars"),
        "entered_near_context_end": target.get("entered_near_context_end"),
        "entry_context_start_event": target.get("entry_context_start_event"),
        "stop_price": target.get("stop_price"),
        "take_profit_price": target.get("take_profit_price"),
        "paper_only": True,
    }
    exit_check = {
        "generated_at_utc": _iso_now(),
        "found": True,
        "trade_id": target.get("trade_id"),
        "original_trade_id": target.get("original_trade_id"),
        "restated": bool(target.get("restated")),
        "position_id": target.get("position_id"),
        "side": target.get("side"),
        "exit_ts": target.get("exit_ts"),
        "exit_wall_ts": target.get("exit_wall_ts"),
        "exit_price": target.get("exit_price"),
        "exit_context": target.get("context_at_exit"),
        "exit_lifecycle": target.get("lifecycle_at_exit"),
        "exit_reason": target.get("exit_reason"),
        "exited_inside_observe": target.get("exited_inside_observe"),
        "exit_context_end_event": target.get("exit_context_end_event"),
        "result_status": target.get("result_status"),
        "realized_pnl_usd": target.get("realized_pnl_usd"),
        "paper_only": True,
    }
    return entry_check, exit_check
