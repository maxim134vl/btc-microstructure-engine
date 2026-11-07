"""REST backfill for Binance Futures aggTrades continuity gaps."""

from __future__ import annotations

from typing import Any, Callable

import requests

FetchAggTradesFn = Callable[[str, int, int], list[dict[str, Any]]]

DEFAULT_FUTURES_AGG_TRADES_URL = "https://fapi.binance.com/fapi/v1/aggTrades"


def default_fetch_agg_trades(symbol: str, from_id: int, to_id: int, *, session: requests.Session | None = None) -> list[dict[str, Any]]:
    if from_id > to_id:
        return []
    out: list[dict[str, Any]] = []
    cursor = int(from_id)
    while cursor <= to_id:
        params = {
            "symbol": symbol.upper(),
            "fromId": cursor,
            "limit": min(1000, to_id - cursor + 1),
        }
        resp = (session.get if session is not None else requests.get)(DEFAULT_FUTURES_AGG_TRADES_URL, params=params, timeout=10)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            # Public exchange error only; no headers/credentials are recorded.
            raise requests.HTTPError(
                f"Binance Futures aggTrades HTTP {resp.status_code} "
                f"symbol={symbol.upper()} fromId={cursor} toId={to_id} "
                f"response={resp.text[:2048]}", response=resp,
            ) from exc
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        last_id = int(batch[-1]["a"])
        if last_id >= to_id:
            break
        cursor = last_id + 1
    return [row for row in out if from_id <= int(row.get("a") or 0) <= to_id]


class ResumeCaptureTransport:
    """One persistent HTTP session, owned solely by one resume capture."""

    def __init__(self) -> None:
        self.session: requests.Session | None = None

    def __call__(self, symbol: str, from_id: int, to_id: int) -> list[dict[str, Any]]:
        if self.session is None:
            self.session = requests.Session()
        return default_fetch_agg_trades(symbol, from_id, to_id, session=self.session)

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None


def normalize_rest_agg_trade(
    row: dict[str, Any],
    *,
    symbol: str,
    connection_session_id: str,
    receive_monotonic_ns: int,
    receive_timestamp: str,
) -> dict[str, Any]:
    agg_id = int(row["a"])
    return {
        "event_type": "AGG_TRADE",
        "symbol": symbol.upper(),
        "aggregate_trade_id": agg_id,
        "exchange_event_timestamp": None,
        "exchange_trade_timestamp": int(row.get("T") or 0),
        "price": str(row.get("p")),
        "quantity": str(row.get("q")),
        "buyer_is_market_maker": bool(row.get("m")),
        "local_receive_timestamp": receive_timestamp,
        "local_receive_monotonic_ns": receive_monotonic_ns,
        "connection_session_id": connection_session_id,
        "source_event_id": f"agg_{agg_id}",
        "backfill": True,
    }
