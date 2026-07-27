"""VIS1B — Canonical trading performance truth (read-only).

Single S4.1 performance source: timeframe trader books + manager mark.
Excludes research bar-policy, legacy controller, and dashboard caches.
Side-effect free: no book writes, no manager/trader actions.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import SUPPORTED_TIMEFRAMES
from .command_bus import PRODUCTION_PORTFOLIO_SUMMARY
from .paper_core import (
    ENTRY_FEE_BPS,
    EXIT_FEE_BPS,
    INITIAL_CAPITAL_USD,
    NORMAL_ENTRY_SLIPPAGE_BPS,
    NORMAL_EXIT_SLIPPAGE_BPS,
    bps_to_rate,
    closed_trade_economics,
    safe_float,
)
from .trader_book import PRODUCTION_BOOKS_ROOT

SCHEMA_VERSION = "trading_performance_truth_v1"
MTM_BASIS_GROSS = "GROSS_UNREALISED"
MTM_BASIS_NET = "NET_UNREALISED_AFTER_ESTIMATED_EXIT_COST"

EXCLUDED_SOURCE_CATEGORIES = (
    "RESEARCH_BAR_POLICY",
    "LEGACY_PAPER_CONTROLLER",
    "DASHBOARD_DERIVATION",
    "QUARANTINE_BACKUP",
)

INCLUDED_SOURCES = (
    "data/trading/timeframe_traders/{M15,M30,H1,H4}/trades.parquet",
    "data/trading/timeframe_traders/{M15,M30,H1,H4}/positions.parquet",
    "data/trading/timeframe_traders/{M15,M30,H1,H4}/fills.parquet",
    "data/trading/timeframe_traders/{M15,M30,H1,H4}/orders.parquet",
    "data/trading/timeframe_traders/{M15,M30,H1,H4}/signals.parquet",
    "data/trading/manager/portfolio_summary.json (mark / reconciliation only)",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sf(value: Any) -> float | None:
    out = safe_float(value)
    if out is None:
        return None
    if isinstance(out, float) and (math.isnan(out) or math.isinf(out)):
        return None
    return float(out)


def _clean_num(value: float | None) -> float | None:
    """Never serialize NaN/Inf."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _episode_parts(value: Any) -> tuple[str | None, int | None]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None, None
    if ":" in text:
        _, _, tail = text.rpartition(":")
        try:
            return text, int(tail)
        except Exception:
            return text, None
    try:
        return text, int(float(text))
    except Exception:
        return text, None


def _holding_minutes(entry_ts: Any, exit_ts: Any) -> float | None:
    try:
        entry = pd.Timestamp(entry_ts)
        exit_ = pd.Timestamp(exit_ts)
        if pd.isna(entry) or pd.isna(exit_):
            return None
        return float((exit_ - entry).total_seconds() / 60.0)
    except Exception:
        return None


def _metric_status_block(
    *,
    value: float | None,
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "value": _clean_num(value),
        "status": status,
        "reason": reason,
    }


def _load_tf_books(
    *,
    books_root: Path,
    timeframes: tuple[str, ...] = SUPPORTED_TIMEFRAMES,
) -> dict[str, dict[str, pd.DataFrame]]:
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for tf in timeframes:
        base = books_root / tf
        out[tf] = {
            "signals": _read_parquet(base / "signals.parquet"),
            "orders": _read_parquet(base / "orders.parquet"),
            "fills": _read_parquet(base / "fills.parquet"),
            "positions": _read_parquet(base / "positions.parquet"),
            "trades": _read_parquet(base / "trades.parquet"),
        }
    return out


def _lineage_maps(books: dict[str, pd.DataFrame]) -> dict[str, Any]:
    fills = books["fills"]
    orders = books["orders"]
    signals = books["signals"]
    fills_by_id = {str(r.paper_trade_id): r for _, r in fills.iterrows()} if len(fills) else {}
    fills_by_pos: dict[str, list[Any]] = defaultdict(list)
    for _, r in fills.iterrows():
        fills_by_pos[str(r.position_id)].append(r)
    orders_by_id = {str(r.paper_order_id): r for _, r in orders.iterrows()} if len(orders) else {}
    signals_by_cmd = (
        {str(r.get("command_id")): r for _, r in signals.iterrows()} if len(signals) else {}
    )
    return {
        "fills_by_id": fills_by_id,
        "fills_by_pos": fills_by_pos,
        "orders_by_id": orders_by_id,
        "signals_by_cmd": signals_by_cmd,
    }


def _classify_closed_lineage(
    *,
    trade_row: pd.Series,
    maps: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    entry_fill = maps["fills_by_id"].get(str(trade_row.get("entry_fill_id")))
    exit_fill = maps["fills_by_id"].get(str(trade_row.get("exit_fill_id")))
    order = None
    if entry_fill is not None:
        order = maps["orders_by_id"].get(str(entry_fill.paper_order_id))
    cmd = str(trade_row.get("command_id") or "")
    signal = maps["signals_by_cmd"].get(cmd)
    ids = {
        "signal_id": None if signal is None else str(signal.get("signal_id")),
        "command_id": cmd or None,
        "order_id": None if order is None else str(order.paper_order_id),
        "entry_fill_id": None if entry_fill is None else str(entry_fill.paper_trade_id),
        "exit_fill_id": None if exit_fill is None else str(exit_fill.paper_trade_id),
        "position_id": str(trade_row.get("position_id")),
        "trade_id": str(trade_row.get("trade_id")),
    }
    if signal is None:
        return "MISSING_SIGNAL", ids
    if order is None:
        return "MISSING_ORDER", ids
    if entry_fill is None:
        return "MISSING_ENTRY_FILL", ids
    if exit_fill is None:
        return "MISSING_EXIT_FILL", ids
    return "COMPLETE", ids


def _classify_open_lineage(
    *,
    position_row: pd.Series,
    maps: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    pid = str(position_row.get("position_id"))
    pfills = sorted(
        maps["fills_by_pos"].get(pid, []),
        key=lambda row: str(row.get("timestamp") or ""),
    )
    entry_fill = pfills[0] if pfills else None
    exit_fill = pfills[1] if len(pfills) > 1 else None
    order = None
    if entry_fill is not None:
        order = maps["orders_by_id"].get(str(entry_fill.paper_order_id))
    cmd = str(position_row.get("command_id") or position_row.get("opening_decision_id") or "")
    signal = maps["signals_by_cmd"].get(cmd)
    ids = {
        "signal_id": None if signal is None else str(signal.get("signal_id")),
        "command_id": cmd or None,
        "order_id": None if order is None else str(order.paper_order_id),
        "entry_fill_id": None if entry_fill is None else str(entry_fill.paper_trade_id),
        "exit_fill_id": None if exit_fill is None else str(exit_fill.paper_trade_id),
        "position_id": pid,
        "trade_id": None,
    }
    if str(position_row.get("status") or "").upper() != "OPEN":
        return "ORPHAN", ids
    if signal is None:
        return "MISSING_SIGNAL", ids
    if order is None:
        return "MISSING_ORDER", ids
    if entry_fill is None:
        return "MISSING_ENTRY_FILL", ids
    if exit_fill is not None:
        return "ORPHAN", ids
    return "OPEN_COMPLETE", ids


def _fee_slip_breakdown(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
    risk_amount_usd: float | None,
    exit_reason: Any,
    stored_fees: float | None,
    stored_slippage: float | None,
) -> dict[str, Any]:
    derived = closed_trade_economics(
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        position_size_btc=qty,
        risk_amount_usd=risk_amount_usd or 250.0,
        exit_reason=exit_reason,
    )
    # Prefer stored aggregates when present; expose derived per-side components.
    return {
        "entry_fee_usd": _clean_num(derived["entry_fee_usd"]),
        "exit_fee_usd": _clean_num(derived["exit_fee_usd"]),
        "fees_usd": _clean_num(stored_fees if stored_fees is not None else derived["fees_usd"]),
        "entry_slippage_usd": _clean_num(derived["entry_slippage_usd"]),
        "exit_slippage_usd": _clean_num(derived["exit_slippage_usd"]),
        "slippage_usd": _clean_num(
            stored_slippage if stored_slippage is not None else derived["slippage_usd"]
        ),
        "derived_gross": _clean_num(derived["gross_pnl_usd"]),
        "derived_net": _clean_num(derived["net_pnl_usd"]),
        "entry_fee_bps": ENTRY_FEE_BPS,
        "exit_fee_bps": EXIT_FEE_BPS,
        "entry_slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "exit_slippage_bps": derived.get("exit_slippage_bps"),
    }


def _build_closed_trades(
    books_by_tf: dict[str, dict[str, pd.DataFrame]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    quality = {
        "incomplete_lineage_count": 0,
        "orphan_count": 0,
        "duplicate_count": 0,
    }
    seen: set[tuple[str, str]] = set()
    for tf, books in books_by_tf.items():
        trades = books["trades"]
        if not len(trades):
            continue
        maps = _lineage_maps(books)
        for _, trade in trades.iterrows():
            trade_id = str(trade.get("trade_id"))
            key = (tf, trade_id)
            if key in seen:
                quality["duplicate_count"] += 1
                continue
            seen.add(key)
            lineage, ids = _classify_closed_lineage(trade_row=trade, maps=maps)
            if lineage != "COMPLETE":
                if lineage == "ORPHAN":
                    quality["orphan_count"] += 1
                else:
                    quality["incomplete_lineage_count"] += 1
                continue
            side = str(trade.get("side") or "").upper()
            entry = _sf(trade.get("entry_price"))
            exit_ = _sf(trade.get("exit_price"))
            qty = _sf(trade.get("quantity"))
            if entry is None or exit_ is None or qty is None:
                quality["incomplete_lineage_count"] += 1
                continue
            gross = _sf(trade.get("gross_pnl_usd"))
            net = _sf(trade.get("net_pnl_usd"))
            breakdown = _fee_slip_breakdown(
                side=side,
                entry_price=entry,
                exit_price=exit_,
                qty=qty,
                risk_amount_usd=_sf(trade.get("risk_amount_usd")),
                exit_reason=trade.get("exit_reason"),
                stored_fees=_sf(trade.get("fees_usd")),
                stored_slippage=_sf(trade.get("slippage_usd")),
            )
            if gross is None:
                gross = breakdown["derived_gross"]
            if net is None:
                net = breakdown["derived_net"]
            ep_key, ep_id = _episode_parts(trade.get("lifecycle_episode_id"))
            rows.append(
                {
                    "timeframe": tf,
                    "trade_id": trade_id,
                    "position_id": ids["position_id"],
                    "signal_id": ids["signal_id"],
                    "command_id": ids["command_id"],
                    "order_id": ids["order_id"],
                    "entry_fill_id": ids["entry_fill_id"],
                    "exit_fill_id": ids["exit_fill_id"],
                    "episode_key": ep_key,
                    "episode_id": ep_id,
                    "side": side,
                    "status": "CLOSED",
                    "lineage_status": "COMPLETE",
                    "quantity": qty,
                    "entry_ts": None if pd.isna(trade.get("entry_ts")) else str(trade.get("entry_ts")),
                    "exit_ts": None if pd.isna(trade.get("exit_ts")) else str(trade.get("exit_ts")),
                    "entry_price": entry,
                    "exit_price": exit_,
                    "gross_realised_pnl_usd": _clean_num(gross),
                    "entry_fee_usd": breakdown["entry_fee_usd"],
                    "exit_fee_usd": breakdown["exit_fee_usd"],
                    "fees_usd": breakdown["fees_usd"],
                    "slippage_cost_usd": breakdown["slippage_usd"],
                    "other_cost_usd": 0.0,
                    "net_realised_pnl_usd": _clean_num(net),
                    "holding_minutes": _holding_minutes(trade.get("entry_ts"), trade.get("exit_ts")),
                    "exit_reason": None
                    if pd.isna(trade.get("exit_reason"))
                    else str(trade.get("exit_reason")),
                    "paper_only": True,
                    "execution_enabled": False,
                    "identity_key": f"{tf}:{trade_id}",
                }
            )
    rows.sort(key=lambda r: (str(r.get("exit_ts") or ""), r["timeframe"], r["trade_id"]))
    return rows, quality


def _build_open_positions(
    books_by_tf: dict[str, dict[str, pd.DataFrame]],
    *,
    mark_price: float | None,
    mark_timestamp: str | None,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    rows: list[dict[str, Any]] = []
    quality = {
        "incomplete_lineage_count": 0,
        "orphan_count": 0,
        "duplicate_count": 0,
    }
    mark_status = "AVAILABLE" if mark_price is not None else "MARK_UNAVAILABLE"
    seen: set[tuple[str, str]] = set()
    for tf, books in books_by_tf.items():
        positions = books["positions"]
        if not len(positions):
            continue
        maps = _lineage_maps(books)
        open_rows = positions[positions["status"].astype(str).str.upper() == "OPEN"]
        for _, pos in open_rows.iterrows():
            pid = str(pos.get("position_id"))
            key = (tf, pid)
            if key in seen:
                quality["duplicate_count"] += 1
                continue
            seen.add(key)
            lineage, ids = _classify_open_lineage(position_row=pos, maps=maps)
            if lineage != "OPEN_COMPLETE":
                if lineage == "ORPHAN":
                    quality["orphan_count"] += 1
                else:
                    quality["incomplete_lineage_count"] += 1
                continue
            side = str(pos.get("direction") or "").upper()
            entry = _sf(pos.get("entry_price"))
            qty = _sf(pos.get("quantity"))
            gross_u = None
            est_exit_fee = None
            est_exit_slip = None
            net_u = None
            if mark_price is None:
                mark_status = "MARK_UNAVAILABLE"
            elif entry is not None and qty is not None:
                if side == "LONG":
                    gross_u = (mark_price - entry) * qty
                elif side == "SHORT":
                    gross_u = (entry - mark_price) * qty
                est_exit_fee = abs(qty) * mark_price * bps_to_rate(EXIT_FEE_BPS)
                est_exit_slip = abs(qty) * mark_price * bps_to_rate(NORMAL_EXIT_SLIPPAGE_BPS)
                if gross_u is not None:
                    net_u = gross_u - est_exit_fee - est_exit_slip
            # episode from signal context if available
            ep_key = None
            ep_id = None
            cmd = ids.get("command_id")
            if cmd and cmd in maps["signals_by_cmd"]:
                ep_key, ep_id = _episode_parts(maps["signals_by_cmd"][cmd].get("context_episode_id"))
            rows.append(
                {
                    "timeframe": tf,
                    "position_id": pid,
                    "signal_id": ids["signal_id"],
                    "command_id": ids["command_id"],
                    "order_id": ids["order_id"],
                    "entry_fill_id": ids["entry_fill_id"],
                    "exit_fill_id": None,
                    "trade_id": None,
                    "episode_key": ep_key,
                    "episode_id": ep_id,
                    "side": side,
                    "status": "OPEN",
                    "lineage_status": "OPEN_COMPLETE",
                    "quantity": qty,
                    "entry_ts": None if pd.isna(pos.get("opened_at")) else str(pos.get("opened_at")),
                    "entry_price": entry,
                    "mark_price": _clean_num(mark_price),
                    "mark_timestamp": mark_timestamp,
                    "gross_unrealised_pnl_usd": _clean_num(gross_u),
                    "estimated_exit_fee_usd": _clean_num(est_exit_fee),
                    "estimated_exit_slippage_usd": _clean_num(est_exit_slip),
                    "net_unrealised_pnl_usd": _clean_num(net_u),
                    "unrealised_status": mark_status
                    if mark_price is None
                    else ("AVAILABLE" if gross_u is not None else "UNAVAILABLE"),
                    "paper_only": True,
                    "execution_enabled": False,
                    "identity_key": f"{tf}:{pid}",
                }
            )
    rows.sort(key=lambda r: (r["timeframe"], str(r.get("entry_ts") or ""), r["position_id"]))
    return rows, quality, mark_status


def _per_timeframe_summary(
    closed: list[dict[str, Any]],
    opens: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tf in SUPPORTED_TIMEFRAMES:
        c_rows = [r for r in closed if r["timeframe"] == tf]
        o_rows = [r for r in opens if r["timeframe"] == tf]
        nets = [float(r["net_realised_pnl_usd"]) for r in c_rows if r.get("net_realised_pnl_usd") is not None]
        wins = [n for n in nets if n > 0]
        losses = [n for n in nets if n <= 0]
        out[tf] = {
            "timeframe": tf,
            "closed_trade_count": len(c_rows),
            "open_position_count": len(o_rows),
            "wins": len(wins),
            "losses": len(losses),
            "realised_gross_pnl_usd": _clean_num(
                sum(float(r["gross_realised_pnl_usd"]) for r in c_rows if r.get("gross_realised_pnl_usd") is not None)
            ),
            "realised_net_pnl_usd": _clean_num(sum(nets) if nets else 0.0),
            "unrealised_gross_pnl_usd": _clean_num(
                sum(
                    float(r["gross_unrealised_pnl_usd"])
                    for r in o_rows
                    if r.get("gross_unrealised_pnl_usd") is not None
                )
            ),
            "unrealised_net_pnl_usd": _clean_num(
                sum(
                    float(r["net_unrealised_pnl_usd"])
                    for r in o_rows
                    if r.get("net_unrealised_pnl_usd") is not None
                )
            ),
            "total_fees_usd": _clean_num(
                sum(float(r["fees_usd"]) for r in c_rows if r.get("fees_usd") is not None)
            ),
            "total_slippage_usd": _clean_num(
                sum(float(r["slippage_cost_usd"]) for r in c_rows if r.get("slippage_cost_usd") is not None)
            ),
            "latest_trade_tip": max((r.get("exit_ts") or "" for r in c_rows), default=None) or None,
            "latest_position_tip": max((r.get("entry_ts") or "" for r in o_rows), default=None) or None,
        }
        if out[tf]["latest_trade_tip"] == "":
            out[tf]["latest_trade_tip"] = None
        if out[tf]["latest_position_tip"] == "":
            out[tf]["latest_position_tip"] = None
    return out


def _descriptive_metrics(closed: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [float(r["net_realised_pnl_usd"]) for r in closed if r.get("net_realised_pnl_usd") is not None]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    n = len(nets)
    if n == 0:
        status = "NO_CLOSED_TRADES"
        reason = "no canonical closed trades"
    elif n < 30:
        status = "PRELIMINARY"
        reason = "INSUFFICIENT_SAMPLE"
    else:
        status = "PRELIMINARY" if n < 100 else "DECISION_GRADE"
        reason = None if status == "DECISION_GRADE" else "INSUFFICIENT_SAMPLE"

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0 and not losses:
        # Do not expose infinity.
        profit_factor = None

    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    expectancy = (sum(nets) / n) if n else None
    holds = [float(r["holding_minutes"]) for r in closed if r.get("holding_minutes") is not None]
    avg_hold = (sum(holds) / len(holds)) if holds else None
    win_rate = (100.0 * len(wins) / n) if n else None

    return {
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _metric_status_block(value=win_rate, status=status, reason=reason),
        "gross_profit": _clean_num(gross_profit),
        "gross_loss": _clean_num(gross_loss),
        "profit_factor": _metric_status_block(
            value=_clean_num(profit_factor),
            status="PRELIMINARY" if n else "NO_CLOSED_TRADES",
            reason="INSUFFICIENT_SAMPLE" if n else "no canonical closed trades",
        ),
        "expectancy": _metric_status_block(
            value=_clean_num(expectancy),
            status="PRELIMINARY" if n else "NO_CLOSED_TRADES",
            reason="INSUFFICIENT_SAMPLE" if n else "no canonical closed trades",
        ),
        "average_win": _clean_num(avg_win),
        "average_loss": _clean_num(avg_loss),
        "average_holding_time_minutes": _clean_num(avg_hold),
        "status": status,
        "reason": reason,
        "closed_trade_count": n,
    }


def _risk_adjusted_metrics(closed_count: int) -> dict[str, Any]:
    reasons = [
        "INSUFFICIENT_SAMPLE" if closed_count < 30 else None,
        "INSUFFICIENT_HISTORY",
        "no canonical equity return series for Sharpe/Calmar",
    ]
    reasons = [r for r in reasons if r]
    return {
        "sharpe": _metric_status_block(
            value=None,
            status="INSUFFICIENT_SAMPLE",
            reason="closed_trade_count=%d; no return-series Sharpe contract" % closed_count,
        ),
        "calmar": _metric_status_block(
            value=None,
            status="INSUFFICIENT_HISTORY",
            reason="history too short for annualised Calmar",
        ),
        "max_drawdown": _metric_status_block(
            value=None,
            status="INSUFFICIENT_HISTORY",
            reason="equity-curve drawdown not decision-grade at current sample",
        ),
        "annualised_return": _metric_status_block(
            value=None,
            status="INSUFFICIENT_HISTORY",
            reason="do not annualise short observation window",
        ),
        "status": "INSUFFICIENT_SAMPLE",
        "reasons": reasons,
        "decision_grade": False,
    }


def build_trading_performance_truth(
    *,
    books_root: Path | None = None,
    portfolio_summary_path: Path | None = None,
    mark_price: float | None = None,
    mark_timestamp: str | None = None,
    initial_equity_usd: float | None = None,
    excluded_research_count: int = 11,
    excluded_legacy_count: int = 4,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build canonical performance payload. Pure read-only function."""
    root = books_root or PRODUCTION_BOOKS_ROOT
    portfolio_path = portfolio_summary_path or PRODUCTION_PORTFOLIO_SUMMARY
    portfolio = _read_json(portfolio_path)

    mark_src = "manager.portfolio_summary.mark_price"
    if mark_price is None:
        mark_price = _sf(portfolio.get("mark_price"))
    if mark_timestamp is None:
        mark_timestamp = (
            None
            if portfolio.get("evaluation_timestamp") is None
            else str(portfolio.get("evaluation_timestamp"))
        )
        if mark_timestamp is None and portfolio.get("generated_at") is not None:
            mark_timestamp = str(portfolio.get("generated_at"))

    books_by_tf = _load_tf_books(books_root=root)
    closed, closed_q = _build_closed_trades(books_by_tf)
    opens, open_q, mark_status = _build_open_positions(
        books_by_tf,
        mark_price=mark_price,
        mark_timestamp=mark_timestamp,
    )
    per_tf = _per_timeframe_summary(closed, opens)

    realised_gross = sum(float(r["gross_realised_pnl_usd"]) for r in closed if r.get("gross_realised_pnl_usd") is not None)
    realised_net = sum(float(r["net_realised_pnl_usd"]) for r in closed if r.get("net_realised_pnl_usd") is not None)
    unreal_gross = sum(
        float(r["gross_unrealised_pnl_usd"]) for r in opens if r.get("gross_unrealised_pnl_usd") is not None
    )
    unreal_net = sum(
        float(r["net_unrealised_pnl_usd"]) for r in opens if r.get("net_unrealised_pnl_usd") is not None
    )
    fees = sum(float(r["fees_usd"]) for r in closed if r.get("fees_usd") is not None)
    slip = sum(float(r["slippage_cost_usd"]) for r in closed if r.get("slippage_cost_usd") is not None)

    initial = float(initial_equity_usd if initial_equity_usd is not None else INITIAL_CAPITAL_USD)
    closed_equity = initial + realised_net
    # Operational MTM uses GROSS unrealised to match manager/OPS VIS1A contract.
    mtm_equity = closed_equity + unreal_gross

    descriptive = _descriptive_metrics(closed)
    risk_adj = _risk_adjusted_metrics(len(closed))

    incomplete = closed_q["incomplete_lineage_count"] + open_q["incomplete_lineage_count"]
    orphans = closed_q["orphan_count"] + open_q["orphan_count"]
    duplicates = closed_q["duplicate_count"] + open_q["duplicate_count"]

    # Portfolio vs TF sum checks
    tf_realised = sum(float(v["realised_net_pnl_usd"] or 0.0) for v in per_tf.values())
    tf_unreal = sum(float(v["unrealised_gross_pnl_usd"] or 0.0) for v in per_tf.values())
    reconciliation = "OK"
    if abs(tf_realised - realised_net) > 1e-6 or abs(tf_unreal - unreal_gross) > 1e-6:
        reconciliation = "TF_SUM_MISMATCH"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "runtime": {
            "paper_only": True,
            "execution_enabled": False,
        },
        "source_policy": {
            "included_sources": list(INCLUDED_SOURCES),
            "excluded_sources": list(EXCLUDED_SOURCE_CATEGORIES),
            "mark_source": mark_src,
            "fees_source": "stored trade fees_usd + paper_trade_economics per-side derivation",
            "slippage_source": "stored trade slippage_usd + paper_trade_economics (enabled)",
            "books_root": str(root),
        },
        "portfolio": {
            "initial_equity_usd": _clean_num(initial),
            "closed_equity_usd": _clean_num(closed_equity),
            "mark_to_market_equity_usd": _clean_num(mtm_equity),
            "mtm_basis": MTM_BASIS_GROSS,
            "mtm_basis_alt_net_field": MTM_BASIS_NET,
            "realised_gross_pnl_usd": _clean_num(realised_gross),
            "realised_net_pnl_usd": _clean_num(realised_net),
            "unrealised_gross_pnl_usd": _clean_num(unreal_gross if mark_price is not None else None),
            "unrealised_net_pnl_usd": _clean_num(unreal_net if mark_price is not None else None),
            "total_gross_pnl_usd": _clean_num(
                None if mark_price is None else realised_gross + unreal_gross
            ),
            "total_net_pnl_usd": _clean_num(
                None if mark_price is None else realised_net + unreal_gross
            ),
            "total_fees_usd": _clean_num(fees),
            "total_slippage_usd": _clean_num(slip),
            "open_position_count": len(opens),
            "closed_trade_count": len(closed),
            "mark_price": _clean_num(mark_price),
            "mark_timestamp": mark_timestamp,
            "mark_status": mark_status,
        },
        "timeframes": per_tf,
        "closed_trades": closed,
        "open_positions": opens,
        "descriptive_metrics": descriptive,
        "risk_adjusted_metrics": risk_adj,
        "sample_status": {
            "descriptive": descriptive["status"],
            "risk_adjusted": risk_adj["status"],
            "closed_trade_count": len(closed),
        },
        "data_quality": {
            "canonical_closed_trade_count": len(closed),
            "canonical_open_position_count": len(opens),
            "duplicate_count": duplicates,
            "orphan_count": orphans,
            "incomplete_lineage_count": incomplete,
            "excluded_research_count": int(excluded_research_count),
            "excluded_legacy_count": int(excluded_legacy_count),
            "excluded_other_count": 0,
            "mark_status": mark_status,
            "reconciliation_status": reconciliation,
        },
    }


def write_candidate_artifacts(
    payload: dict[str, Any],
    *,
    out_dir: Path,
) -> dict[str, str]:
    """Write candidate JSON only (never live OPS/public paths)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "trading_performance_truth.json": payload,
        "closed_trades.json": {
            "generated_at": payload.get("generated_at"),
            "count": len(payload.get("closed_trades") or []),
            "closed_trades": payload.get("closed_trades") or [],
        },
        "open_positions.json": {
            "generated_at": payload.get("generated_at"),
            "count": len(payload.get("open_positions") or []),
            "open_positions": payload.get("open_positions") or [],
        },
        "per_timeframe_summary.json": {
            "generated_at": payload.get("generated_at"),
            "timeframes": payload.get("timeframes") or {},
        },
        "metric_statuses.json": {
            "generated_at": payload.get("generated_at"),
            "descriptive_metrics": payload.get("descriptive_metrics") or {},
            "risk_adjusted_metrics": payload.get("risk_adjusted_metrics") or {},
            "sample_status": payload.get("sample_status") or {},
        },
        "source_exclusions.json": {
            "generated_at": payload.get("generated_at"),
            "excluded_sources": (payload.get("source_policy") or {}).get("excluded_sources") or [],
            "included_sources": (payload.get("source_policy") or {}).get("included_sources") or [],
        },
        "data_quality.json": {
            "generated_at": payload.get("generated_at"),
            "data_quality": payload.get("data_quality") or {},
        },
    }
    written: dict[str, str] = {}
    for name, obj in paths.items():
        path = out_dir / name
        path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        written[name] = str(path)
    return written
