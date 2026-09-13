"""USD-M order payloads and Binance clientOrderId mapping."""

from __future__ import annotations

import hashlib
import re
from typing import Any

CLIENT_ORDER_ID_RE = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")


def client_order_id_for(command_id: str) -> str:
    text = str(command_id or "").strip()
    if not text:
        raise ValueError("command_id required")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    value = "s41" + digest[:33]
    if not CLIENT_ORDER_ID_RE.match(value):
        raise ValueError(f"invalid clientOrderId {value!r}")
    return value


def aggressive_limit_price(*, side: str, mid: float, ioc_slippage_bps: float, tick_size: float) -> float:
    mid_f = float(mid)
    slip = float(ioc_slippage_bps) / 10_000.0
    side_u = str(side).upper()
    if side_u == "LONG":
        raw = mid_f * (1.0 + slip)
        return _round_tick(raw, tick_size, mode="up")
    if side_u == "SHORT":
        raw = mid_f * (1.0 - slip)
        return _round_tick(raw, tick_size, mode="down")
    raise ValueError(f"unsupported side={side!r}")


def _round_tick(price: float, tick: float, *, mode: str) -> float:
    if tick <= 0:
        raise ValueError("tick_size must be > 0")
    n = price / tick
    if mode == "up":
        import math

        n = math.ceil(n - 1e-12)
    elif mode == "down":
        import math

        n = math.floor(n + 1e-12)
    else:
        n = round(n)
    return float(n * tick)


def ioc_limit_order(
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    client_order_id: str,
    reduce_only: bool = False,
) -> dict[str, Any]:
    buy = str(side).upper() == "LONG"
    payload = {
        "symbol": symbol,
        "side": "BUY" if buy else "SELL",
        "type": "LIMIT",
        "timeInForce": "IOC",
        "quantity": _qty_str(quantity),
        "price": _px_str(price),
        "newClientOrderId": client_order_id,
        "newOrderRespType": "RESULT",
    }
    if reduce_only:
        payload["reduceOnly"] = "true"
    return payload


def market_order(
    *,
    symbol: str,
    side: str,
    quantity: float,
    client_order_id: str,
    reduce_only: bool = False,
) -> dict[str, Any]:
    buy = str(side).upper() == "LONG"
    payload = {
        "symbol": symbol,
        "side": "BUY" if buy else "SELL",
        "type": "MARKET",
        "quantity": _qty_str(quantity),
        "newClientOrderId": client_order_id,
        "newOrderRespType": "RESULT",
    }
    if reduce_only:
        payload["reduceOnly"] = "true"
    return payload


def stop_market_close(
    *,
    symbol: str,
    position_side: str,
    stop_price: float,
    client_order_id: str,
    close_position: bool = True,
    quantity: float | None = None,
) -> dict[str, Any]:
    protective_buy = str(position_side).upper() == "SHORT"
    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": "BUY" if protective_buy else "SELL",
        "type": "STOP_MARKET",
        "stopPrice": _px_str(stop_price),
        "workingType": "MARK_PRICE",
        "newClientOrderId": client_order_id,
        "newOrderRespType": "RESULT",
    }
    if close_position:
        payload["closePosition"] = "true"
    elif quantity is not None:
        payload["quantity"] = _qty_str(quantity)
        payload["reduceOnly"] = "true"
    return payload


def take_profit_market_close(
    *,
    symbol: str,
    position_side: str,
    take_price: float,
    client_order_id: str,
    close_position: bool = True,
    quantity: float | None = None,
) -> dict[str, Any]:
    protective_buy = str(position_side).upper() == "SHORT"
    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": "BUY" if protective_buy else "SELL",
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": _px_str(take_price),
        "workingType": "CONTRACT_PRICE",
        "newClientOrderId": client_order_id,
        "newOrderRespType": "RESULT",
    }
    if close_position:
        payload["closePosition"] = "true"
    elif quantity is not None:
        payload["quantity"] = _qty_str(quantity)
        payload["reduceOnly"] = "true"
    return payload


def _qty_str(quantity: float) -> str:
    text = f"{float(quantity):.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _px_str(price: float) -> str:
    text = f"{float(price):.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def protective_side(entry_side: str) -> str:
    return "SHORT" if str(entry_side).upper() == "LONG" else "LONG"
