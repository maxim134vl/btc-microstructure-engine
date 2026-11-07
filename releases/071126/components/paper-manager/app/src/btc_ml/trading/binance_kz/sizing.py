"""1% of live PM equity. Never uses paper $100k. CatBoost re-capped to 1%."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import CATBOOST_CLIP_HI, CATBOOST_CLIP_LO, RISK_PCT


@dataclass(frozen=True)
class LiveSizing:
    ok: bool
    block_reason: str | None
    side: str
    entry_price: float
    stop_price: float
    take_price: float
    stop_distance: float
    equity_usd: float
    risk_usd: float
    catboost_mult: float
    quantity: float | None
    notional_usd: float | None
    initial_margin_usd: float | None


def bps_to_rate(bps: float) -> float:
    return float(bps) / 10_000.0


def clip_catboost_mult(value: float) -> float:
    return float(min(CATBOOST_CLIP_HI, max(CATBOOST_CLIP_LO, float(value))))


def stop_take_prices(*, side: str, entry_price: float, stop_loss_bps: float, take_profit_bps: float) -> tuple[float, float]:
    side_u = str(side).upper()
    stop_dist = entry_price * bps_to_rate(stop_loss_bps)
    take_dist = entry_price * bps_to_rate(take_profit_bps)
    if side_u == "LONG":
        return entry_price - stop_dist, entry_price + take_dist
    if side_u == "SHORT":
        return entry_price + stop_dist, entry_price - take_dist
    raise ValueError(f"unsupported side={side!r}")


def round_step_down(value: float, step: float) -> float:
    if step <= 0:
        raise ValueError("step must be > 0")
    return float(math.floor((value / step) + 1e-12) * step)


def resolve_live_sizing(
    *,
    side: str,
    entry_price: float,
    equity_usd: float,
    stop_loss_bps: float,
    take_profit_bps: float,
    leverage: int,
    catboost_mult: float = 1.0,
    qty_step: float = 0.001,
    risk_pct: float = RISK_PCT,
) -> LiveSizing:
    side_u = str(side).upper()
    if side_u not in {"LONG", "SHORT"}:
        return LiveSizing(False, "ENTRY_BLOCKED_BAD_SIDE", side_u, entry_price, 0.0, 0.0, 0.0, equity_usd, 0.0, 1.0, None, None, None)
    if entry_price <= 0 or equity_usd <= 0:
        return LiveSizing(
            False, "ENTRY_BLOCKED_INVALID_EQUITY_OR_PRICE", side_u, entry_price, 0.0, 0.0, 0.0, equity_usd, 0.0, 1.0, None, None, None
        )
    mult = clip_catboost_mult(catboost_mult)
    cap_risk = float(equity_usd) * float(risk_pct) / 100.0
    risk_usd = min(cap_risk, cap_risk * mult)
    stop_px, take_px = stop_take_prices(
        side=side_u,
        entry_price=entry_price,
        stop_loss_bps=stop_loss_bps,
        take_profit_bps=take_profit_bps,
    )
    stop_distance = abs(entry_price - stop_px)
    if stop_distance <= 0 or risk_usd <= 0:
        return LiveSizing(
            False,
            "ENTRY_BLOCKED_INVALID_STOP_DISTANCE",
            side_u,
            entry_price,
            stop_px,
            take_px,
            stop_distance,
            equity_usd,
            risk_usd,
            mult,
            None,
            None,
            None,
        )
    raw_qty = risk_usd / stop_distance
    qty = round_step_down(raw_qty, qty_step)
    if qty <= 0:
        return LiveSizing(
            False,
            "ENTRY_BLOCKED_QTY_ROUNDS_TO_ZERO",
            side_u,
            entry_price,
            stop_px,
            take_px,
            stop_distance,
            equity_usd,
            risk_usd,
            mult,
            None,
            None,
            None,
        )
    implied_risk = qty * stop_distance
    if implied_risk > cap_risk + 1e-9:
        qty = round_step_down(cap_risk / stop_distance, qty_step)
        implied_risk = qty * stop_distance
        risk_usd = min(risk_usd, implied_risk)
    notional = qty * entry_price
    margin = notional / float(leverage) if leverage > 0 else None
    return LiveSizing(
        True,
        None,
        side_u,
        entry_price,
        stop_px,
        take_px,
        stop_distance,
        equity_usd,
        risk_usd,
        mult,
        qty,
        notional,
        margin,
    )
