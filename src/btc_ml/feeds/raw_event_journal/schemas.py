"""Canonical schemas for raw market event journal."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = "1.0.0"


class StreamType(str, Enum):
    AGG_TRADE = "AGG_TRADE"
    BOOK_TICKER = "BOOK_TICKER"
    OPERATIONAL = "OPERATIONAL"


class OperationalEventType(str, Enum):
    STREAM_CONNECTED = "STREAM_CONNECTED"
    STREAM_DISCONNECTED = "STREAM_DISCONNECTED"
    STREAM_RECONNECTING = "STREAM_RECONNECTING"
    STREAM_RECONNECTED = "STREAM_RECONNECTED"
    SEQUENCE_GAP_DETECTED = "SEQUENCE_GAP_DETECTED"
    DUPLICATE_DROPPED = "DUPLICATE_DROPPED"
    WRITER_FLUSHED = "WRITER_FLUSHED"
    WRITER_RECOVERED = "WRITER_RECOVERED"
    COLLECTION_STARTED = "COLLECTION_STARTED"
    COLLECTION_STOPPED = "COLLECTION_STOPPED"
    DISK_LOW = "DISK_LOW"
    HEALTH_STATUS_CHANGED = "HEALTH_STATUS_CHANGED"
    RAW_EVENT_BACKPRESSURE = "RAW_EVENT_BACKPRESSURE"
    BUFFERED_EVENTS_LOST = "BUFFERED_EVENTS_LOST"


AGG_TRADE_REQUIRED_FIELDS = (
    "schema_version",
    "stream_type",
    "symbol",
    "exchange_event_timestamp",
    "exchange_trade_timestamp",
    "local_receive_timestamp",
    "local_receive_monotonic_ns",
    "aggregate_trade_id",
    "first_trade_id",
    "last_trade_id",
    "price",
    "quantity",
    "quote_quantity",
    "buyer_is_market_maker",
    "connection_session_id",
    "reconnect_generation",
    "source_sequence",
    "raw_payload_hash",
    "ingested_at",
)

BOOK_TICKER_REQUIRED_FIELDS = (
    "schema_version",
    "stream_type",
    "symbol",
    "exchange_event_timestamp",
    "local_receive_timestamp",
    "local_receive_monotonic_ns",
    "update_id",
    "best_bid_price",
    "best_bid_quantity",
    "best_ask_price",
    "best_ask_quantity",
    "spread",
    "mid_price",
    "connection_session_id",
    "reconnect_generation",
    "source_sequence",
    "raw_payload_hash",
    "ingested_at",
)

OPERATIONAL_REQUIRED_FIELDS = (
    "schema_version",
    "stream_type",
    "event_type",
    "symbol",
    "local_receive_timestamp",
    "local_receive_monotonic_ns",
    "connection_session_id",
    "reconnect_generation",
    "details",
    "ingested_at",
)


def validate_event(event: Mapping[str, Any], stream: StreamType) -> list[str]:
    """Return list of schema violations (empty if valid)."""
    errors: list[str] = []
    if stream is StreamType.AGG_TRADE:
        required = AGG_TRADE_REQUIRED_FIELDS
    elif stream is StreamType.BOOK_TICKER:
        required = BOOK_TICKER_REQUIRED_FIELDS
    else:
        required = OPERATIONAL_REQUIRED_FIELDS
    for field in required:
        if field not in event:
            errors.append(f"missing_field:{field}")
    if event.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version:{event.get('schema_version')}")
    expected_type = stream.value
    if event.get("stream_type") != expected_type:
        errors.append(f"stream_type:{event.get('stream_type')}")
    return errors
