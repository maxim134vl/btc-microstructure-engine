"""Parquet schemas for raw market event journal (Decimal128, ZSTD)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

import pyarrow as pa

from .schemas import SCHEMA_VERSION, StreamType

# Binance price/qty strings commonly use 8 fractional digits.
DECIMAL_PRECISION = 38
DECIMAL_SCALE = 8
DECIMAL_TYPE = pa.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE)


def _dec_field(name: str) -> pa.Field:
    return pa.field(name, DECIMAL_TYPE, nullable=True)


AGG_TRADE_ARROW_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string()),
        pa.field("stream_type", pa.string()),
        pa.field("symbol", pa.string()),
        pa.field("exchange_event_timestamp", pa.string(), nullable=True),
        pa.field("exchange_trade_timestamp", pa.string(), nullable=True),
        pa.field("local_receive_timestamp", pa.string()),
        pa.field("local_receive_monotonic_ns", pa.int64()),
        pa.field("aggregate_trade_id", pa.int64(), nullable=True),
        pa.field("first_trade_id", pa.int64(), nullable=True),
        pa.field("last_trade_id", pa.int64(), nullable=True),
        _dec_field("price"),
        _dec_field("quantity"),
        _dec_field("quote_quantity"),
        pa.field("buyer_is_market_maker", pa.bool_(), nullable=True),
        pa.field("connection_session_id", pa.string(), nullable=True),
        pa.field("reconnect_generation", pa.int32()),
        pa.field("source_sequence", pa.int64()),
        pa.field("raw_payload_hash", pa.string()),
        pa.field("ingested_at", pa.string()),
    ]
)

BOOK_TICKER_ARROW_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string()),
        pa.field("stream_type", pa.string()),
        pa.field("symbol", pa.string()),
        pa.field("exchange_event_timestamp", pa.string(), nullable=True),
        pa.field("local_receive_timestamp", pa.string()),
        pa.field("local_receive_monotonic_ns", pa.int64()),
        pa.field("update_id", pa.int64(), nullable=True),
        _dec_field("best_bid_price"),
        _dec_field("best_bid_quantity"),
        _dec_field("best_ask_price"),
        _dec_field("best_ask_quantity"),
        _dec_field("spread"),
        _dec_field("mid_price"),
        pa.field("connection_session_id", pa.string(), nullable=True),
        pa.field("reconnect_generation", pa.int32()),
        pa.field("source_sequence", pa.int64()),
        pa.field("raw_payload_hash", pa.string()),
        pa.field("ingested_at", pa.string()),
    ]
)

OPERATIONAL_ARROW_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string()),
        pa.field("stream_type", pa.string()),
        pa.field("event_type", pa.string()),
        pa.field("symbol", pa.string()),
        pa.field("local_receive_timestamp", pa.string()),
        pa.field("local_receive_monotonic_ns", pa.int64()),
        pa.field("connection_session_id", pa.string(), nullable=True),
        pa.field("reconnect_generation", pa.int32()),
        pa.field("details_json", pa.string()),
        pa.field("ingested_at", pa.string()),
    ]
)


def arrow_schema_for(stream: StreamType) -> pa.Schema:
    if stream is StreamType.AGG_TRADE:
        return AGG_TRADE_ARROW_SCHEMA
    if stream is StreamType.BOOK_TICKER:
        return BOOK_TICKER_ARROW_SCHEMA
    return OPERATIONAL_ARROW_SCHEMA


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal(10) ** -DECIMAL_SCALE)
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text).quantize(Decimal(10) ** -DECIMAL_SCALE)


def format_decimal_text(value: Any) -> Optional[str]:
    """Canonical fixed-scale text (8 dp) restoring Binance-style strings."""
    if value is None:
        return None
    dec = to_decimal(value)
    if dec is None:
        return None
    return format(dec, f".{DECIMAL_SCALE}f")


def event_to_arrow_row(stream: StreamType, event: Mapping[str, Any]) -> dict[str, Any]:
    if stream is StreamType.AGG_TRADE:
        return {
            "schema_version": event.get("schema_version", SCHEMA_VERSION),
            "stream_type": event.get("stream_type"),
            "symbol": event.get("symbol"),
            "exchange_event_timestamp": event.get("exchange_event_timestamp"),
            "exchange_trade_timestamp": event.get("exchange_trade_timestamp"),
            "local_receive_timestamp": event.get("local_receive_timestamp"),
            "local_receive_monotonic_ns": event.get("local_receive_monotonic_ns"),
            "aggregate_trade_id": event.get("aggregate_trade_id"),
            "first_trade_id": event.get("first_trade_id"),
            "last_trade_id": event.get("last_trade_id"),
            "price": to_decimal(event.get("price")),
            "quantity": to_decimal(event.get("quantity")),
            "quote_quantity": to_decimal(event.get("quote_quantity")),
            "buyer_is_market_maker": event.get("buyer_is_market_maker"),
            "connection_session_id": event.get("connection_session_id"),
            "reconnect_generation": int(event.get("reconnect_generation") or 0),
            "source_sequence": int(event.get("source_sequence") or 0),
            "raw_payload_hash": event.get("raw_payload_hash"),
            "ingested_at": event.get("ingested_at"),
        }
    if stream is StreamType.BOOK_TICKER:
        return {
            "schema_version": event.get("schema_version", SCHEMA_VERSION),
            "stream_type": event.get("stream_type"),
            "symbol": event.get("symbol"),
            "exchange_event_timestamp": event.get("exchange_event_timestamp"),
            "local_receive_timestamp": event.get("local_receive_timestamp"),
            "local_receive_monotonic_ns": event.get("local_receive_monotonic_ns"),
            "update_id": event.get("update_id"),
            "best_bid_price": to_decimal(event.get("best_bid_price")),
            "best_bid_quantity": to_decimal(event.get("best_bid_quantity")),
            "best_ask_price": to_decimal(event.get("best_ask_price")),
            "best_ask_quantity": to_decimal(event.get("best_ask_quantity")),
            "spread": to_decimal(event.get("spread")),
            "mid_price": to_decimal(event.get("mid_price")),
            "connection_session_id": event.get("connection_session_id"),
            "reconnect_generation": int(event.get("reconnect_generation") or 0),
            "source_sequence": int(event.get("source_sequence") or 0),
            "raw_payload_hash": event.get("raw_payload_hash"),
            "ingested_at": event.get("ingested_at"),
        }
    import json

    details = event.get("details") or {}
    return {
        "schema_version": event.get("schema_version", SCHEMA_VERSION),
        "stream_type": event.get("stream_type"),
        "event_type": event.get("event_type"),
        "symbol": event.get("symbol"),
        "local_receive_timestamp": event.get("local_receive_timestamp"),
        "local_receive_monotonic_ns": event.get("local_receive_monotonic_ns"),
        "connection_session_id": event.get("connection_session_id"),
        "reconnect_generation": int(event.get("reconnect_generation") or 0),
        "details_json": json.dumps(details, ensure_ascii=True, separators=(",", ":")),
        "ingested_at": event.get("ingested_at"),
    }


def arrow_row_to_event(stream: StreamType, row: Mapping[str, Any]) -> dict[str, Any]:
    """Rehydrate canonical event dict from a Parquet row via Decimal128 → text."""
    if stream is StreamType.AGG_TRADE:
        return {
            "schema_version": row.get("schema_version"),
            "stream_type": row.get("stream_type"),
            "symbol": row.get("symbol"),
            "exchange_event_timestamp": row.get("exchange_event_timestamp"),
            "exchange_trade_timestamp": row.get("exchange_trade_timestamp"),
            "local_receive_timestamp": row.get("local_receive_timestamp"),
            "local_receive_monotonic_ns": int(row["local_receive_monotonic_ns"])
            if row.get("local_receive_monotonic_ns") is not None
            else None,
            "aggregate_trade_id": row.get("aggregate_trade_id"),
            "first_trade_id": row.get("first_trade_id"),
            "last_trade_id": row.get("last_trade_id"),
            "price": format_decimal_text(row.get("price")),
            "quantity": format_decimal_text(row.get("quantity")),
            "quote_quantity": format_decimal_text(row.get("quote_quantity")),
            "buyer_is_market_maker": row.get("buyer_is_market_maker"),
            "connection_session_id": row.get("connection_session_id"),
            "reconnect_generation": int(row.get("reconnect_generation") or 0),
            "source_sequence": int(row.get("source_sequence") or 0),
            "raw_payload_hash": row.get("raw_payload_hash"),
            "ingested_at": row.get("ingested_at"),
        }
    if stream is StreamType.BOOK_TICKER:
        return {
            "schema_version": row.get("schema_version"),
            "stream_type": row.get("stream_type"),
            "symbol": row.get("symbol"),
            "exchange_event_timestamp": row.get("exchange_event_timestamp"),
            "local_receive_timestamp": row.get("local_receive_timestamp"),
            "local_receive_monotonic_ns": int(row["local_receive_monotonic_ns"])
            if row.get("local_receive_monotonic_ns") is not None
            else None,
            "update_id": row.get("update_id"),
            "best_bid_price": format_decimal_text(row.get("best_bid_price")),
            "best_bid_quantity": format_decimal_text(row.get("best_bid_quantity")),
            "best_ask_price": format_decimal_text(row.get("best_ask_price")),
            "best_ask_quantity": format_decimal_text(row.get("best_ask_quantity")),
            "spread": format_decimal_text(row.get("spread")),
            "mid_price": format_decimal_text(row.get("mid_price")),
            "connection_session_id": row.get("connection_session_id"),
            "reconnect_generation": int(row.get("reconnect_generation") or 0),
            "source_sequence": int(row.get("source_sequence") or 0),
            "raw_payload_hash": row.get("raw_payload_hash"),
            "ingested_at": row.get("ingested_at"),
        }
    import json

    details_raw = row.get("details_json") or "{}"
    try:
        details = json.loads(details_raw)
    except json.JSONDecodeError:
        details = {"_raw": details_raw}
    return {
        "schema_version": row.get("schema_version"),
        "stream_type": row.get("stream_type"),
        "event_type": row.get("event_type"),
        "symbol": row.get("symbol"),
        "local_receive_timestamp": row.get("local_receive_timestamp"),
        "local_receive_monotonic_ns": int(row["local_receive_monotonic_ns"])
        if row.get("local_receive_monotonic_ns") is not None
        else None,
        "connection_session_id": row.get("connection_session_id"),
        "reconnect_generation": int(row.get("reconnect_generation") or 0),
        "details": details,
        "ingested_at": row.get("ingested_at"),
    }
