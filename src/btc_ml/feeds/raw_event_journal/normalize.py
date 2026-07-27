"""Payload normalization for aggTrade and bookTicker."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from .precision import compute_spread_mid, decimal_from_payload
from .schemas import SCHEMA_VERSION, StreamType
from .timestamps import ms_to_utc_iso, utc_now_iso


def _payload_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def normalize_agg_trade(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    local_receive_timestamp: str,
    local_receive_monotonic_ns: int,
    connection_session_id: str,
    reconnect_generation: int,
    source_sequence: int,
    retain_raw_payload: bool = False,
) -> dict[str, Any]:
    """Normalize Binance aggTrade payload. Missing fields → null (never synthesized)."""
    price = decimal_from_payload(payload.get("p"))
    qty = decimal_from_payload(payload.get("q"))
    quote_qty = None
    if price is not None and qty is not None:
        # Derived from exact decimal strings; still deterministic from payload.
        from decimal import Decimal

        quote_qty = format(Decimal(price) * Decimal(qty), "f")

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stream_type": StreamType.AGG_TRADE.value,
        "symbol": symbol,
        "exchange_event_timestamp": ms_to_utc_iso(payload.get("E")),
        "exchange_trade_timestamp": ms_to_utc_iso(payload.get("T")),
        "local_receive_timestamp": local_receive_timestamp,
        "local_receive_monotonic_ns": int(local_receive_monotonic_ns),
        "aggregate_trade_id": _optional_int(payload.get("a")),
        "first_trade_id": _optional_int(payload.get("f")),
        "last_trade_id": _optional_int(payload.get("l")),
        "price": price,
        "quantity": qty,
        "quote_quantity": quote_qty,
        "buyer_is_market_maker": _optional_bool(payload.get("m")),
        "connection_session_id": connection_session_id,
        "reconnect_generation": int(reconnect_generation),
        "source_sequence": int(source_sequence),
        "raw_payload_hash": _payload_hash(dict(payload)),
        "ingested_at": utc_now_iso(),
    }
    if retain_raw_payload:
        event["raw_payload"] = dict(payload)
    return event


def normalize_book_ticker(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    local_receive_timestamp: str,
    local_receive_monotonic_ns: int,
    connection_session_id: str,
    reconnect_generation: int,
    source_sequence: int,
    retain_raw_payload: bool = False,
) -> dict[str, Any]:
    """Normalize Binance bookTicker. exchange_event_timestamp stays null if absent."""
    bid = decimal_from_payload(payload.get("b"))
    bid_qty = decimal_from_payload(payload.get("B"))
    ask = decimal_from_payload(payload.get("a"))
    ask_qty = decimal_from_payload(payload.get("A"))
    spread, mid = compute_spread_mid(bid, ask)

    # Prefer E if present; never substitute local time.
    exchange_ts = ms_to_utc_iso(payload.get("E"))

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stream_type": StreamType.BOOK_TICKER.value,
        "symbol": symbol,
        "exchange_event_timestamp": exchange_ts,
        "local_receive_timestamp": local_receive_timestamp,
        "local_receive_monotonic_ns": int(local_receive_monotonic_ns),
        "update_id": _optional_int(payload.get("u")),
        "best_bid_price": bid,
        "best_bid_quantity": bid_qty,
        "best_ask_price": ask,
        "best_ask_quantity": ask_qty,
        "spread": spread,
        "mid_price": mid,
        "connection_session_id": connection_session_id,
        "reconnect_generation": int(reconnect_generation),
        "source_sequence": int(source_sequence),
        "raw_payload_hash": _payload_hash(dict(payload)),
        "ingested_at": utc_now_iso(),
    }
    if retain_raw_payload:
        event["raw_payload"] = dict(payload)
    return event


def normalize_operational(
    event_type: str,
    *,
    symbol: str,
    local_receive_timestamp: str,
    local_receive_monotonic_ns: int,
    connection_session_id: Optional[str],
    reconnect_generation: int,
    details: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stream_type": StreamType.OPERATIONAL.value,
        "event_type": event_type,
        "symbol": symbol,
        "local_receive_timestamp": local_receive_timestamp,
        "local_receive_monotonic_ns": int(local_receive_monotonic_ns),
        "connection_session_id": connection_session_id,
        "reconnect_generation": int(reconnect_generation),
        "details": dict(details or {}),
        "ingested_at": utc_now_iso(),
    }
