"""Vault-equity risk sizing. Never uses paper $100k as the notional base."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VaultSizing:
    ok: bool
    block_reason: str | None
    side: str
    entry_price: float
    stop_price: float
    take_price: float
    stop_distance: float
    risk_usd: float
    quantity: float | None
    notional_usd: float | None
    capped_by_hard_cap: bool


def bps_to_rate(bps: float) -> float:
    return float(bps) / 10_000.0


def stop_take_prices(*, side: str, entry_price: float, stop_loss_bps: float, take_profit_bps: float) -> tuple[float, float]:
    side_u = str(side).upper()
    stop_dist = entry_price * bps_to_rate(stop_loss_bps)
    take_dist = entry_price * bps_to_rate(take_profit_bps)
    if side_u == "LONG":
        return entry_price - stop_dist, entry_price + take_dist
    if side_u == "SHORT":
        return entry_price + stop_dist, entry_price - take_dist
    raise ValueError(f"unsupported side={side!r}")


def round_size(quantity: float, sz_decimals: int) -> float:
    if sz_decimals < 0:
        raise ValueError("sz_decimals must be >= 0")
    scale = 10 ** int(sz_decimals)
    return float(int(quantity * scale) / scale)


def resolve_vault_sizing(
    *,
    side: str,
    entry_price: float,
    vault_equity_usd: float,
    max_risk_per_trade_pct: float,
    max_risk_per_trade_usd: float,
    stop_loss_bps: float,
    take_profit_bps: float,
    hard_cap_order_btc: float,
    sz_decimals: int = 5,
) -> VaultSizing:
    side_u = str(side).upper()
    if side_u not in {"LONG", "SHORT"}:
        return VaultSizing(False, "ENTRY_BLOCKED_BAD_SIDE", side_u, entry_price, 0.0, 0.0, 0.0, 0.0, None, None, False)
    if entry_price <= 0 or vault_equity_usd <= 0:
        return VaultSizing(False, "ENTRY_BLOCKED_INVALID_EQUITY_OR_PRICE", side_u, entry_price, 0.0, 0.0, 0.0, 0.0, None, None, False)
    pct_budget = vault_equity_usd * float(max_risk_per_trade_pct) / 100.0
    risk_usd = min(float(max_risk_per_trade_usd), pct_budget)
    if risk_usd <= 0:
        return VaultSizing(False, "ENTRY_BLOCKED_ZERO_RISK", side_u, entry_price, 0.0, 0.0, 0.0, risk_usd, None, None, False)
    stop_px, take_px = stop_take_prices(
        side=side_u,
        entry_price=entry_price,
        stop_loss_bps=stop_loss_bps,
        take_profit_bps=take_profit_bps,
    )
    stop_distance = abs(entry_price - stop_px)
    if stop_distance <= 0:
        return VaultSizing(
            False, "ENTRY_BLOCKED_INVALID_STOP_DISTANCE", side_u, entry_price, stop_px, take_px, stop_distance, risk_usd, None, None, False
        )
    raw_qty = risk_usd / stop_distance
    capped = raw_qty > float(hard_cap_order_btc) > 0
    qty = min(raw_qty, float(hard_cap_order_btc)) if float(hard_cap_order_btc) > 0 else raw_qty
    qty = round_size(qty, sz_decimals)
    if qty <= 0:
        return VaultSizing(
            False, "ENTRY_BLOCKED_QTY_ROUNDS_TO_ZERO", side_u, entry_price, stop_px, take_px, stop_distance, risk_usd, None, None, capped
        )
    return VaultSizing(
        True,
        None,
        side_u,
        entry_price,
        stop_px,
        take_px,
        stop_distance,
        risk_usd,
        qty,
        qty * entry_price,
        capped,
    )
