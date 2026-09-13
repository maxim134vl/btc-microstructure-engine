"""Reconcile POST /order HTTP 503 unknown. Never issues a second POST."""

from __future__ import annotations

from typing import Any

from .client import OrderUnknownError, PortfolioMarginExchange
from .constants import SYMBOL


def place_or_reconcile(
    client: PortfolioMarginExchange,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Place once. On unknown, GET by origClientOrderId."""
    cid = str(params.get("newClientOrderId") or "").strip()
    try:
        return client.place_um_order(params)
    except OrderUnknownError as exc:
        lookup = cid or str(exc.client_order_id or "")
        if not lookup:
            raise
        return client.get_um_order(orig_client_order_id=lookup, symbol=str(params.get("symbol") or SYMBOL))
