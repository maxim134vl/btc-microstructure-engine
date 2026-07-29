"""Cost-aware risk sizing and closed-trade economics for LIVE1B."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import IntrabarPaperConfig


def bps_to_rate(bps: float) -> float:
    return float(bps) / 10_000.0


@dataclass
class RiskSizing:
    ok: bool
    block_reason: str | None
    side: str
    entry_price: float | None
    stop_loss_price: float | None
    take_profit_price: float | None
    stop_distance: float | None
    risk_amount_usd: float
    quantity: float | None
    entry_notional: float | None
    per_btc_cost: float | None
    estimated_loss: float | None
    entry_fee_usd: float | None
    stop_exit_fee_usd: float | None
    entry_slippage_usd: float | None
    stop_exit_slippage_usd: float | None


def stop_take_prices(*, side: str, entry: float, stop_bps: float, take_bps: float) -> tuple[float, float]:
    side_u = str(side).upper()
    if side_u == "LONG":
        stop = entry * (1.0 - bps_to_rate(stop_bps))
        take = entry * (1.0 + bps_to_rate(take_bps))
    else:
        stop = entry * (1.0 + bps_to_rate(stop_bps))
        take = entry * (1.0 - bps_to_rate(take_bps))
    return stop, take


def stop_distance(side: str, entry: float, stop: float) -> float:
    side_u = str(side).upper()
    if side_u == "LONG":
        return max(0.0, entry - stop)
    return max(0.0, stop - entry)


def resolve_risk_sizing(
    *,
    cfg: IntrabarPaperConfig,
    side: str,
    entry_price: float,
    equity_usd: float | None = None,
    risk_budget_usd: float | None = None,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
) -> RiskSizing:
    """Cost-aware risk sizing.

    Optional stop_loss_price / take_profit_price let research shadows feed
    structural levels through the same helper without a second sizing formula.
    LIVE1B default path leaves both None and keeps configured bps geometry.
    """
    side_u = str(side).upper()
    entry = float(entry_price)
    if stop_loss_price is None or take_profit_price is None:
        cfg_stop, cfg_take = stop_take_prices(
            side=side_u,
            entry=entry,
            stop_bps=cfg.stop_loss_bps,
            take_bps=cfg.take_profit_bps,
        )
        stop = float(stop_loss_price) if stop_loss_price is not None else cfg_stop
        take = float(take_profit_price) if take_profit_price is not None else cfg_take
    else:
        stop = float(stop_loss_price)
        take = float(take_profit_price)
    # Risk budget: min(1% equity, configured max) — do NOT divide across TFs.
    # Optional risk_budget_usd lets a derived capital model feed the same path
    # without reimplementing cost-aware sizing.
    if risk_budget_usd is not None:
        risk_amount = float(risk_budget_usd)
    else:
        eq = float(equity_usd if equity_usd is not None else cfg.initial_equity_usd)
        risk_pct = eq * (cfg.max_risk_per_trade_pct / 100.0)
        risk_amount = min(risk_pct, float(cfg.max_risk_per_trade_usd))
    if entry <= 0 or stop <= 0:
        return RiskSizing(
            False,
            "ENTRY_BLOCKED_NO_VALID_STOP_FOR_RISK_SIZING",
            side_u,
            entry,
            stop,
            take,
            None,
            risk_amount,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    dist = stop_distance(side_u, entry, stop)
    if dist <= 0:
        return RiskSizing(
            False,
            "ENTRY_BLOCKED_INVALID_STOP_DISTANCE",
            side_u,
            entry,
            stop,
            take,
            dist,
            risk_amount,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    if cfg.fixed_notional:
        return RiskSizing(
            False,
            "ENTRY_BLOCKED_FIXED_NOTIONAL_DISABLED",
            side_u,
            entry,
            stop,
            take,
            dist,
            risk_amount,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    per_btc = (
        dist
        + entry * bps_to_rate(cfg.entry_fee_bps)
        + stop * bps_to_rate(cfg.exit_fee_bps)
        + entry * bps_to_rate(cfg.entry_slippage_bps)
        + stop * bps_to_rate(cfg.stop_exit_slippage_bps)
    )
    if per_btc <= 0:
        return RiskSizing(
            False,
            "ENTRY_BLOCKED_INVALID_STOP_DISTANCE",
            side_u,
            entry,
            stop,
            take,
            dist,
            risk_amount,
            None,
            None,
            per_btc,
            None,
            None,
            None,
            None,
            None,
        )
    qty = risk_amount / per_btc
    entry_notional = qty * entry
    stop_notional = qty * stop
    entry_fee = entry_notional * bps_to_rate(cfg.entry_fee_bps)
    stop_exit_fee = stop_notional * bps_to_rate(cfg.exit_fee_bps)
    entry_slip = entry_notional * bps_to_rate(cfg.entry_slippage_bps)
    stop_exit_slip = stop_notional * bps_to_rate(cfg.stop_exit_slippage_bps)
    estimated = qty * dist + entry_fee + stop_exit_fee + entry_slip + stop_exit_slip
    return RiskSizing(
        True,
        None,
        side_u,
        entry,
        stop,
        take,
        dist,
        risk_amount,
        qty,
        entry_notional,
        per_btc,
        estimated,
        entry_fee,
        stop_exit_fee,
        entry_slip,
        stop_exit_slip,
    )


def closed_trade_economics(
    *,
    cfg: IntrabarPaperConfig,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    risk_amount_usd: float,
    exit_reason: str | None = None,
) -> dict[str, Any]:
    side_u = str(side).upper()
    entry = float(entry_price)
    exit_ = float(exit_price)
    qty = abs(float(quantity))
    exit_slip_bps = (
        cfg.stop_exit_slippage_bps
        if str(exit_reason or "").upper() in {"SL", "STOP", "STOP_LOSS"}
        else cfg.exit_slippage_bps
    )
    entry_notional = qty * entry
    exit_notional = qty * exit_
    gross = (entry - exit_) * qty if side_u == "SHORT" else (exit_ - entry) * qty
    entry_fee = entry_notional * bps_to_rate(cfg.entry_fee_bps)
    exit_fee = exit_notional * bps_to_rate(cfg.exit_fee_bps)
    entry_slip = entry_notional * bps_to_rate(cfg.entry_slippage_bps)
    exit_slip = exit_notional * bps_to_rate(exit_slip_bps)
    fees = entry_fee + exit_fee
    slippage = entry_slip + exit_slip
    net = gross - fees - slippage
    return {
        "side": side_u,
        "gross_entry_price": entry,
        "gross_exit_price": exit_,
        "entry_fee_usd": entry_fee,
        "exit_fee_usd": exit_fee,
        "configured_entry_slippage_bps": cfg.entry_slippage_bps,
        "configured_exit_slippage_bps": exit_slip_bps,
        "entry_slippage_usd": entry_slip,
        "exit_slippage_usd": exit_slip,
        "fees_usd": fees,
        "slippage_usd": slippage,
        "gross_pnl_usd": gross,
        "net_pnl_usd": net,
        "risk_amount_usd": float(risk_amount_usd),
        "r_multiple": (net / risk_amount_usd) if risk_amount_usd else 0.0,
    }
