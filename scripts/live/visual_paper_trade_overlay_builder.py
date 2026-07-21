#!/usr/bin/env python3
"""Build paper trade position overlays for the lifecycle visualizer (visual-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = ROOT / "data" / "research" / "paper_simulator"
DECISION_LOG = ROOT / "data" / "live" / "context_decision_log.parquet"
LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"

SYNTHETIC_BAND = (99000.0, 101000.0)
DEFAULT_INITIAL_CAPITAL = 100000.0


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


def build_paper_overlays(mark_price: float | None = None) -> dict[str, Any]:
    signals = _load_parquet(PAPER_DIR / "paper_signals.parquet")
    orders = _load_parquet(PAPER_DIR / "paper_orders.parquet")
    trades = _load_parquet(PAPER_DIR / "paper_trades.parquet")
    positions = _load_parquet(PAPER_DIR / "paper_positions.parquet")
    equity = _load_parquet(PAPER_DIR / "paper_equity_curve.parquet")
    risk = _load_parquet(PAPER_DIR / "paper_risk_blocks.parquet")

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

        wall_entry = _iso_ts(row.get("opened_at"))
        wall_exit = _iso_ts(row.get("closed_at"))
        chart_entry = entry_candle_ts or wall_entry
        chart_exit = exit_candle_ts or wall_exit

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

    closed_sorted = sorted(closed_overlays, key=lambda x: x.get("exit_wall_ts") or x.get("exit_ts") or "")
    last_closed = closed_sorted[-1] if closed_sorted else None

    return {
        "generated_at_utc": _iso_now(),
        "paper_only": True,
        "execution_enabled": False,
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
        },
        "entries": entries,
        "exits": exits,
        "trade_shapes": trade_shapes,
        "open_positions": open_overlays,
        "closed_trades": closed_overlays,
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
        }
    return {
        "generated_at_utc": _iso_now(),
        "has_closed_trade": True,
        "trade_id": last.get("trade_id"),
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
        "paper_only": True,
        "execution_enabled": False,
    }


def build_pnl_summary(overlays: dict[str, Any]) -> dict[str, Any]:
    equity = _load_parquet(PAPER_DIR / "paper_equity_curve.parquet")
    initial_capital = None
    initial_source = "DEFAULT_100000_FALLBACK"
    current_equity = None
    first_ts = None
    last_ts = None

    if len(equity):
        # Prefer metadata paper_initial_equity_usd, else first equity + fees heuristic.
        for _, row in equity.iterrows():
            meta = _meta(row)
            cand = _safe_float(meta.get("paper_initial_equity_usd"))
            if cand is not None:
                initial_capital = cand
                initial_source = "paper_equity_metadata_paper_initial_equity_usd"
                break
        first = equity.iloc[0]
        last = equity.iloc[-1]
        first_ts = _iso_ts(first.get("timestamp"))
        last_ts = _iso_ts(last.get("timestamp"))
        current_equity = _safe_float(last.get("equity"))
        if initial_capital is None:
            # Reconstruct approx initial from earliest snapshot cash/equity + entry fee if present.
            initial_capital = _safe_float(first.get("equity"))
            fee0 = _safe_float(first.get("fees_paid")) or 0.0
            if initial_capital is not None:
                initial_capital = round(initial_capital + fee0, 6)
                initial_source = "paper_equity_first_row_plus_fees"
    if initial_capital is None:
        initial_capital = DEFAULT_INITIAL_CAPITAL
        initial_source = "DEFAULT_100000_FALLBACK"
    if current_equity is None:
        current_equity = initial_capital

    total_pnl_usd = round(float(current_equity) - float(initial_capital), 6)
    total_pnl_pct = round((float(current_equity) / float(initial_capital) - 1.0) * 100.0, 6)

    elapsed_days = 0.0
    t0 = _parse_ts(first_ts)
    t1 = _parse_ts(last_ts) or datetime.now(timezone.utc)
    if t0 is not None:
        elapsed_days = max(0.0, (t1 - t0).total_seconds() / 86400.0)
    if elapsed_days > 0 and initial_capital > 0:
        annualized = ((float(current_equity) / float(initial_capital)) ** (365.0 / elapsed_days) - 1.0) * 100.0
        annualized_return_pct = round(annualized, 6)
    else:
        annualized_return_pct = 0.0

    closed = overlays.get("closed_trades") or []
    open_pos = overlays.get("open_positions") or []
    wins = sum(1 for c in closed if c.get("result_status") == "WIN")
    losses = sum(1 for c in closed if c.get("result_status") == "LOSS")

    return {
        "generated_at_utc": _iso_now(),
        "initial_capital": initial_capital,
        "initial_capital_source": initial_source,
        "current_paper_equity": current_equity,
        "total_pnl_usd": total_pnl_usd,
        "total_pnl_pct": total_pnl_pct,
        "annualized_return_pct": annualized_return_pct,
        "elapsed_days": round(elapsed_days, 6),
        "closed_trades_count": len(closed),
        "win_count": wins,
        "loss_count": losses,
        "open_positions_count": len(open_pos),
        "paper_only": True,
        "execution_enabled": False,
    }


def build_trade_context_checks(overlays: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    closed = overlays.get("closed_trades") or []
    target = None
    for c in closed:
        if c.get("entry_price") is not None and abs(float(c["entry_price"]) - 65913.0) < 1.0:
            target = c
            break
    if target is None and closed:
        target = sorted(closed, key=lambda x: x.get("exit_wall_ts") or "")[-1]

    if target is None:
        empty = {"generated_at_utc": _iso_now(), "found": False}
        return empty, empty

    entry_check = {
        "generated_at_utc": _iso_now(),
        "found": True,
        "trade_id": target.get("trade_id"),
        "position_id": target.get("position_id"),
        "side": target.get("side"),
        "entry_ts": target.get("entry_ts"),
        "entry_wall_ts": target.get("entry_wall_ts"),
        "entry_price": target.get("entry_price"),
        "entry_context": target.get("context_at_entry"),
        "entry_lifecycle": target.get("lifecycle_at_entry"),
        "entry_context_age_bars": target.get("entry_context_age_bars"),
        "entered_near_context_end": target.get("entered_near_context_end"),
        "stop_price": target.get("stop_price"),
        "take_profit_price": target.get("take_profit_price"),
        "paper_only": True,
    }
    exit_check = {
        "generated_at_utc": _iso_now(),
        "found": True,
        "trade_id": target.get("trade_id"),
        "position_id": target.get("position_id"),
        "side": target.get("side"),
        "exit_ts": target.get("exit_ts"),
        "exit_wall_ts": target.get("exit_wall_ts"),
        "exit_price": target.get("exit_price"),
        "exit_context": target.get("context_at_exit"),
        "exit_lifecycle": target.get("lifecycle_at_exit"),
        "exit_reason": target.get("exit_reason"),
        "exited_inside_observe": target.get("exited_inside_observe"),
        "result_status": target.get("result_status"),
        "realized_pnl_usd": target.get("realized_pnl_usd"),
        "paper_only": True,
    }
    return entry_check, exit_check
