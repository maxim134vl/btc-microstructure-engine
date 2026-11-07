"""Shared causal mark / unrealized helpers for LIVE1B presentation.

Mark contract matches paper exit fill selection:
  LONG  → best bid
  SHORT → best ask
"""

from __future__ import annotations

from typing import Any

from .bbo import CausalBBO, fill_price_for


def mark_price_for_side(*, side: str, best_bid: float, best_ask: float) -> float:
    """Return causal mark for open-position MTM (same side as EXIT fill)."""
    bbo = CausalBBO(
        book_update_id=None,
        best_bid=float(best_bid),
        best_ask=float(best_ask),
        receive_timestamp=None,
        receive_monotonic_ns=0,
    )
    return float(fill_price_for(side=side, action="EXIT", bbo=bbo))


def unrealized_pnl_usd(
    *,
    side: str,
    entry_price: float,
    quantity: float,
    mark_price: float,
) -> float:
    """Gross unrealized PnL using causal mark (bid for LONG, ask for SHORT)."""
    side_u = str(side).upper()
    entry = float(entry_price)
    qty = float(quantity)
    mark = float(mark_price)
    if side_u == "LONG":
        return (mark - entry) * qty
    if side_u == "SHORT":
        return (entry - mark) * qty
    raise ValueError(f"unknown side {side}")


def mark_side_label(side: str) -> str:
    side_u = str(side).upper()
    if side_u == "LONG":
        return "bid"
    if side_u == "SHORT":
        return "ask"
    return "unknown"


def position_notional_usd(*, quantity: float, entry_price: float) -> float:
    return abs(float(quantity) * float(entry_price))


def risk_reward_ratio(
    *,
    side: str,
    entry_price: float,
    stop_loss_price: float | None,
    take_profit_price: float | None,
) -> float | None:
    if stop_loss_price is None or take_profit_price is None:
        return None
    entry = float(entry_price)
    stop = float(stop_loss_price)
    take = float(take_profit_price)
    side_u = str(side).upper()
    if side_u == "LONG":
        stop_dist = entry - stop
        take_dist = take - entry
    elif side_u == "SHORT":
        stop_dist = stop - entry
        take_dist = entry - take
    else:
        return None
    if stop_dist <= 0:
        return None
    return take_dist / stop_dist
