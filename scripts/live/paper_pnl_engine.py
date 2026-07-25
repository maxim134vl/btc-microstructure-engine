#!/usr/bin/env python3
"""Shared paper trading PnL math for research/visual accounting.

This module is visual/research infrastructure only. It does not write ledgers
and does not place or alter orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from math import sqrt
from statistics import median
from typing import Any, Iterable

import pandas as pd

from paper_trade_economics import (
    ECONOMICS_SOURCE,
    ENTRY_FEE_BPS,
    INITIAL_CAPITAL_USD,
    MAX_RISK_PER_TRADE_PCT,
    NORMAL_ENTRY_SLIPPAGE_BPS,
    POSITION_SIZING_MODE,
    STOP_LOSS_BPS,
    TAKE_PROFIT_BPS,
    closed_trade_economics,
    resolve_risk_sizing,
    stop_take_prices as canonical_stop_take_prices,
)

INITIAL_CAPITAL = INITIAL_CAPITAL_USD
FEE_BPS_PER_SIDE = ENTRY_FEE_BPS
SLIPPAGE_USD = 0.0
CALENDAR_DAYS_PER_YEAR = 365.0
LOW_SAMPLE_SIZE_MIN_RETURNS = 30
SIZING_MODE = POSITION_SIZING_MODE


@dataclass(frozen=True)
class PaperTradeMath:
    stop_loss_price: float
    take_profit_price: float
    stop_distance: float
    risk_amount: float
    position_size_btc: float
    position_notional: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    fees: float
    entry_slippage: float
    exit_slippage: float
    slippage: float
    slippage_bps: float
    slippage_R: float
    net_pnl: float
    r_multiple: float
    sizing_status: str
    economics_source: str


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        if pd.isna(out):
            return None
        return out
    except Exception:
        return None


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    except Exception:
        return None


def stop_take_prices(
    side: str,
    entry_price: float,
    *,
    stop_loss_bps: float = STOP_LOSS_BPS,
    take_profit_bps: float = TAKE_PROFIT_BPS,
) -> tuple[float, float]:
    if float(stop_loss_bps) == STOP_LOSS_BPS and float(take_profit_bps) == TAKE_PROFIT_BPS:
        stop, take = canonical_stop_take_prices(side, entry_price)
    else:
        side_u = str(side or "").upper()
        entry = float(entry_price)
        if side_u == "SHORT":
            stop = entry * (1.0 + float(stop_loss_bps) / 10000.0)
            take = entry * (1.0 - float(take_profit_bps) / 10000.0)
        else:
            stop = entry * (1.0 - float(stop_loss_bps) / 10000.0)
            take = entry * (1.0 + float(take_profit_bps) / 10000.0)
    return round(stop, 8), round(take, 8)


def compute_trade_math(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    initial_capital: float = INITIAL_CAPITAL,
    max_risk_per_trade_pct: float = MAX_RISK_PER_TRADE_PCT,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
    fee_bps_per_side: float = FEE_BPS_PER_SIDE,
    slippage: float = SLIPPAGE_USD,
    exit_reason: Any = None,
    exit_execution_source: Any = None,
) -> PaperTradeMath:
    side_u = str(side or "").upper()
    entry = float(entry_price)
    exit_ = float(exit_price)
    derived_stop, derived_take = stop_take_prices(side_u, entry)
    stop = float(stop_loss_price) if stop_loss_price is not None else derived_stop
    take = float(take_profit_price) if take_profit_price is not None else derived_take
    sizing = resolve_risk_sizing(side=side_u, entry_price=entry, stop_loss_price=stop, take_profit_price=take)
    risk_amount = float(initial_capital) * float(max_risk_per_trade_pct) / 100.0
    stop_distance = abs(entry - stop)
    sizing_status = "RISK_BASED_DERIVED_STOP" if stop_loss_price is None else "RISK_BASED_EXPLICIT_STOP"
    if not sizing.allowed:
        qty = 0.0
        notional = 0.0
        sizing_status = "NO_VALID_STOP_DISTANCE"
    else:
        qty = float(sizing.position_size_btc or 0.0)
        notional = float(sizing.position_notional_usd or 0.0)
    economics = closed_trade_economics(
        side=side_u,
        entry_price=entry,
        exit_price=exit_,
        position_size_btc=qty,
        stop_loss_price=stop,
        take_profit_price=take,
        risk_amount_usd=risk_amount,
        exit_reason=exit_reason,
        exit_execution_source=exit_execution_source,
    )
    gross = float(economics["gross_pnl_before_fees_slippage"])
    entry_fee = float(economics["entry_fee_usd"])
    exit_fee = float(economics["exit_fee_usd"])
    fees = float(economics["fees_usd"])
    entry_slippage = float(economics["entry_slippage_usd"])
    exit_slippage = float(economics["exit_slippage_usd"])
    total_slippage = float(economics["slippage_usd"])
    if slippage not in (None, 0.0, 0):
        total_slippage = float(slippage)
    net = gross - fees - total_slippage
    r_multiple = net / risk_amount if risk_amount else 0.0
    return PaperTradeMath(
        stop_loss_price=round(stop, 8),
        take_profit_price=round(take, 8),
        stop_distance=round(stop_distance, 8),
        risk_amount=round(risk_amount, 6),
        position_size_btc=qty,
        position_notional=round(notional, 6),
        gross_pnl=round(gross, 6),
        entry_fee=round(entry_fee, 6),
        exit_fee=round(exit_fee, 6),
        fees=round(fees, 6),
        entry_slippage=round(entry_slippage, 6),
        exit_slippage=round(exit_slippage, 6),
        slippage=round(total_slippage, 6),
        slippage_bps=round(float(economics["slippage_bps"]), 6),
        slippage_R=round(float(economics["slippage_R"]), 8),
        net_pnl=round(net, 6),
        r_multiple=round(r_multiple, 6),
        sizing_status=sizing_status,
        economics_source=ECONOMICS_SOURCE,
    )


def _sum_numeric(rows: Iterable[dict[str, Any]], key: str) -> float:
    return sum(float(_safe_float(r.get(key)) or 0.0) for r in rows)


def _max_streak(results: list[bool]) -> int:
    best = 0
    cur = 0
    for result in results:
        if result:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _max_drawdown(equity_points: list[dict[str, Any]]) -> tuple[float, float, str]:
    peak = None
    peak_ts: pd.Timestamp | None = None
    underwater_since: pd.Timestamp | None = None
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    max_duration_seconds = 0.0
    for point in equity_points:
        equity = float(point["equity"])
        ts = _parse_ts(point.get("timestamp"))
        if peak is None or equity >= peak:
            peak = equity
            peak_ts = ts
            underwater_since = None
            continue
        if peak <= 0:
            continue
        dd_usd = equity - peak
        dd_pct = dd_usd / peak * 100.0
        if underwater_since is None:
            underwater_since = peak_ts
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd
        if underwater_since is not None and ts is not None:
            max_duration_seconds = max(max_duration_seconds, (ts - underwater_since).total_seconds())
    if max_duration_seconds <= 0:
        duration = "0m"
    elif max_duration_seconds < 86400:
        duration = f"{max_duration_seconds / 3600.0:.2f}h"
    else:
        duration = f"{max_duration_seconds / 86400.0:.2f}d"
    return round(max_dd_pct, 6), round(max_dd_usd, 6), duration


def build_equity_curve(
    trades: list[dict[str, Any]],
    *,
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda t: str(t.get("exit_ts") or t.get("entry_ts") or ""))
    start_ts = _parse_ts(ordered[0].get("entry_ts")) if ordered else pd.Timestamp.now(tz=timezone.utc)
    equity = float(initial_capital)
    curve = [{"timestamp": start_ts.isoformat().replace("+00:00", "Z"), "equity": round(equity, 6), "trade_id": None}]
    for trade in ordered:
        equity += float(_safe_float(trade.get("net_pnl")) or 0.0)
        ts = _parse_ts(trade.get("exit_ts") or trade.get("entry_ts")) or start_ts
        curve.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "equity": round(equity, 6),
                "trade_id": trade.get("trade_id"),
            }
        )
    return curve


def summarize_trades(
    trades: list[dict[str, Any]],
    *,
    initial_capital: float = INITIAL_CAPITAL,
    open_positions_count: int = 0,
    unrealized_pnl: float = 0.0,
) -> dict[str, Any]:
    closed = list(trades)
    equity_curve = build_equity_curve(closed, initial_capital=initial_capital)
    net_values = [float(_safe_float(t.get("net_pnl")) or 0.0) for t in closed]
    wins = [v for v in net_values if v >= 0.0]
    losses = [v for v in net_values if v < 0.0]
    r_values = [float(_safe_float(t.get("r_multiple")) or 0.0) for t in closed]
    gross_values = [float(_safe_float(t.get("gross_pnl")) or 0.0) for t in closed]
    gross_profit = sum(v for v in net_values if v > 0.0)
    gross_loss = sum(v for v in net_values if v < 0.0)
    total_net = sum(net_values)
    current_equity = float(initial_capital) + total_net + float(unrealized_pnl)
    win_count = len(wins)
    loss_count = len(losses)
    closed_count = len(closed)
    win_rate = (win_count / closed_count * 100.0) if closed_count else 0.0
    loss_rate = (loss_count / closed_count * 100.0) if closed_count else 0.0
    best = max(closed, key=lambda t: float(_safe_float(t.get("net_pnl")) or 0.0), default=None)
    worst = min(closed, key=lambda t: float(_safe_float(t.get("net_pnl")) or 0.0), default=None)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    max_dd_pct, max_dd_usd, max_dd_duration = _max_drawdown(equity_curve)

    returns: list[float] = []
    equities = [float(p["equity"]) for p in equity_curve]
    for prev, cur in zip(equities, equities[1:]):
        if prev:
            returns.append((cur / prev) - 1.0)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    if len(returns) > 1:
        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = sqrt(variance)
        downside = [min(0.0, r) for r in returns]
        downside_variance = sum(r**2 for r in downside) / (len(downside) - 1) if len(downside) > 1 else 0.0
        downside_std = sqrt(downside_variance)
    else:
        std_return = 0.0
        downside_std = 0.0

    start_ts = _parse_ts(equity_curve[0].get("timestamp")) if equity_curve else None
    end_ts = _parse_ts(equity_curve[-1].get("timestamp")) if equity_curve else None
    elapsed_days = 0.0
    if start_ts is not None and end_ts is not None:
        elapsed_days = max(0.0, (end_ts - start_ts).total_seconds() / 86400.0)
    annualization_periods = len(returns)
    if elapsed_days > 0 and annualization_periods:
        periods_per_year = annualization_periods / (elapsed_days / CALENDAR_DAYS_PER_YEAR)
    else:
        periods_per_year = CALENDAR_DAYS_PER_YEAR
    sharpe = (mean_return / std_return * sqrt(periods_per_year)) if std_return else 0.0
    sortino = (mean_return / downside_std * sqrt(periods_per_year)) if downside_std else 0.0
    total_return = (current_equity / float(initial_capital) - 1.0) if initial_capital else 0.0
    if elapsed_days > 0 and initial_capital > 0:
        daily_return = (current_equity / float(initial_capital)) ** (1.0 / elapsed_days) - 1.0
        annualized_return = (current_equity / float(initial_capital)) ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0
    else:
        daily_return = total_return
        annualized_return = total_return
    calmar = (annualized_return * 100.0 / abs(max_dd_pct)) if max_dd_pct else 0.0
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss else (0.0 if gross_profit == 0 else "Infinity")
    recovery_factor = (total_net / abs(max_dd_usd)) if max_dd_usd else (0.0 if total_net == 0 else None)
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss else (0.0 if avg_win == 0 else None)

    holding_minutes: list[float] = []
    exposure_seconds = 0.0
    for trade in closed:
        a = _parse_ts(trade.get("entry_ts"))
        b = _parse_ts(trade.get("exit_ts"))
        if a is not None and b is not None:
            seconds = max(0.0, (b - a).total_seconds())
            holding_minutes.append(seconds / 60.0)
            exposure_seconds += seconds
    elapsed_seconds = elapsed_days * 86400.0
    exposure_time_pct = exposure_seconds / elapsed_seconds * 100.0 if elapsed_seconds else 0.0
    trades_per_day = closed_count / elapsed_days if elapsed_days else float(closed_count)
    result_bools = [v >= 0.0 for v in net_values]

    risk_amount = float(initial_capital) * MAX_RISK_PER_TRADE_PCT / 100.0
    detailed = {
        "initial_capital": round(float(initial_capital), 6),
        "current_equity": round(current_equity, 6),
        "realized_pnl": round(total_net, 6),
        "unrealized_pnl": round(float(unrealized_pnl), 6),
        "total_pnl": round(total_net + float(unrealized_pnl), 6),
        "total_return_pct": round(total_return * 100.0, 6),
        "daily_return_pct": round(daily_return * 100.0, 6),
        "annualized_return_pct": round(annualized_return * 100.0, 6),
        "closed_trades": closed_count,
        "open_positions": int(open_positions_count),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_pct": round(win_rate, 6),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "best_trade": None if best is None else {"trade_id": best.get("trade_id"), "net_pnl": best.get("net_pnl")},
        "worst_trade": None if worst is None else {"trade_id": worst.get("trade_id"), "net_pnl": worst.get("net_pnl")},
        "fees_paid": round(_sum_numeric(closed, "fees"), 6),
        "fees_paid_usd": round(_sum_numeric(closed, "fees"), 6),
        "slippage_paid": round(_sum_numeric(closed, "slippage"), 6),
        "slippage_paid_usd": round(_sum_numeric(closed, "slippage"), 6),
        "gross_pnl_before_costs_usd": round(sum(gross_values), 6),
        "net_pnl_after_costs_usd": round(total_net, 6),
        "position_sizing_mode": SIZING_MODE,
        "risk_amount": round(risk_amount, 6),
        "risk_amount_usd": round(risk_amount, 6),
        "risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
        "sizing_status": "RISK_BASED_DERIVED_STOP",
        "economics_source": ECONOMICS_SOURCE,
    }
    metrics = {
        "sharpe_ratio": round(sharpe, 6),
        "sortino_ratio": round(sortino, 6),
        "calmar_ratio": round(calmar, 6),
        "max_drawdown_pct": round(max_dd_pct, 6),
        "max_drawdown_usd": round(max_dd_usd, 6),
        "max_drawdown_duration": max_dd_duration,
        "profit_factor": profit_factor if isinstance(profit_factor, str) else round(profit_factor, 6),
        "recovery_factor": None if recovery_factor is None else round(recovery_factor, 6),
        "expectancy_per_trade": round(total_net / closed_count, 6) if closed_count else 0.0,
        "expectancy_r": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "average_r": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_r": round(median(r_values), 6) if r_values else 0.0,
        "best_r": round(max(r_values), 6) if r_values else 0.0,
        "worst_r": round(min(r_values), 6) if r_values else 0.0,
        "payoff_ratio": None if payoff_ratio is None else round(payoff_ratio, 6),
        "average_holding_time": f"{sum(holding_minutes) / len(holding_minutes):.2f}m" if holding_minutes else "0m",
        "average_holding_minutes": round(sum(holding_minutes) / len(holding_minutes), 6) if holding_minutes else 0.0,
        "exposure_time_pct": round(exposure_time_pct, 6),
        "trades_per_day": round(trades_per_day, 6),
        "win_rate_pct": round(win_rate, 6),
        "loss_rate_pct": round(loss_rate, 6),
        "consecutive_wins": _max_streak(result_bools),
        "consecutive_losses": _max_streak([not r for r in result_bools]),
        "sample_size": len(returns),
        "status": "low sample size" if len(returns) < LOW_SAMPLE_SIZE_MIN_RETURNS else "ok",
        "annualization": {
            "basis": "calendar_days",
            "days_per_year": CALENDAR_DAYS_PER_YEAR,
            "periods_per_year": round(periods_per_year, 6),
            "returns_source": "equity_curve",
        },
    }
    return {
        "detailed_pnl": detailed,
        "model_evaluation_metrics": metrics,
        "equity_curve": equity_curve,
    }
