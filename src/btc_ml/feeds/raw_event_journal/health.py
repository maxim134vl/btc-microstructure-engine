"""Health snapshot statuses for the shadow collector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    EVENT_SEQUENCE_GAP = "EVENT_SEQUENCE_GAP"
    STREAM_STALE = "STREAM_STALE"
    WRITER_BLOCKED = "WRITER_BLOCKED"
    DISK_ERROR = "DISK_ERROR"
    DISK_LOW = "DISK_LOW"
    SCHEMA_ERROR = "SCHEMA_ERROR"


@dataclass
class HealthSnapshot:
    process_alive: bool = True
    connection_state: str = "DISCONNECTED"
    health_status: str = HealthStatus.HEALTHY.value
    last_agg_trade_receive_time: Optional[str] = None
    last_book_ticker_receive_time: Optional[str] = None
    events_received: int = 0
    agg_trade_received: int = 0
    book_ticker_received: int = 0
    events_committed: int = 0
    duplicates_dropped: int = 0
    gaps_detected: int = 0
    current_buffer_size: int = 0
    last_committed_batch: Optional[str] = None
    write_errors: int = 0
    reconnect_count: int = 0
    collection_started_at: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
