"""Bounded in-memory event queue between receive path and archival writer."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional

from .schemas import StreamType


@dataclass
class QueuedEvent:
    stream: StreamType
    event: dict[str, Any]
    enqueue_monotonic_ns: int
    estimated_bytes: int


@dataclass
class QueueMetrics:
    queue_current_events: int = 0
    queue_current_bytes: int = 0
    queue_capacity_events: int = 0
    queue_capacity_bytes: int = 0
    queue_high_watermark_events: int = 0
    queue_high_watermark_bytes: int = 0
    enqueue_latency_ms_last: float = 0.0
    enqueue_latency_ms_max: float = 0.0
    writer_lag_ms_last: float = 0.0
    writer_lag_ms_max: float = 0.0
    enqueue_ok: int = 0
    enqueue_rejected: int = 0
    dequeued: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_current_events": self.queue_current_events,
            "queue_current_bytes": self.queue_current_bytes,
            "queue_capacity_events": self.queue_capacity_events,
            "queue_capacity_bytes": self.queue_capacity_bytes,
            "queue_high_watermark": self.queue_high_watermark_events,
            "queue_high_watermark_events": self.queue_high_watermark_events,
            "queue_high_watermark_bytes": self.queue_high_watermark_bytes,
            "enqueue_latency_ms": self.enqueue_latency_ms_last,
            "enqueue_latency_ms_max": self.enqueue_latency_ms_max,
            "writer_lag_ms": self.writer_lag_ms_last,
            "writer_lag_ms_max": self.writer_lag_ms_max,
            "enqueue_ok": self.enqueue_ok,
            "enqueue_rejected": self.enqueue_rejected,
            "dequeued": self.dequeued,
        }


def estimate_event_bytes(event: dict[str, Any]) -> int:
    try:
        return len(json.dumps(event, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return 512


@dataclass
class BoundedEventQueue:
    """Fail-closed bounded queue. Never silently drops events."""

    capacity_events: int = 50_000
    capacity_bytes: int = 64 * 1024 * 1024
    _q: Deque[QueuedEvent] = field(default_factory=deque)
    _bytes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _not_empty: threading.Condition = field(init=False)
    metrics: QueueMetrics = field(default_factory=QueueMetrics)
    closed: bool = False

    def __post_init__(self) -> None:
        self._not_empty = threading.Condition(self._lock)
        self.metrics.queue_capacity_events = self.capacity_events
        self.metrics.queue_capacity_bytes = self.capacity_bytes

    def try_enqueue(self, stream: StreamType, event: dict[str, Any]) -> bool:
        """Enqueue with no disk I/O. Returns False on backpressure (no drop)."""
        t0 = time.monotonic()
        size = estimate_event_bytes(event)
        item = QueuedEvent(
            stream=stream,
            event=event,
            enqueue_monotonic_ns=time.monotonic_ns(),
            estimated_bytes=size,
        )
        with self._not_empty:
            if self.closed:
                self.metrics.enqueue_rejected += 1
                return False
            if (
                len(self._q) >= self.capacity_events
                or self._bytes + size > self.capacity_bytes
            ):
                self.metrics.enqueue_rejected += 1
                self.metrics.queue_current_events = len(self._q)
                self.metrics.queue_current_bytes = self._bytes
                return False
            self._q.append(item)
            self._bytes += size
            self.metrics.enqueue_ok += 1
            self.metrics.queue_current_events = len(self._q)
            self.metrics.queue_current_bytes = self._bytes
            if len(self._q) > self.metrics.queue_high_watermark_events:
                self.metrics.queue_high_watermark_events = len(self._q)
            if self._bytes > self.metrics.queue_high_watermark_bytes:
                self.metrics.queue_high_watermark_bytes = self._bytes
            latency_ms = (time.monotonic() - t0) * 1000.0
            self.metrics.enqueue_latency_ms_last = round(latency_ms, 4)
            if latency_ms > self.metrics.enqueue_latency_ms_max:
                self.metrics.enqueue_latency_ms_max = round(latency_ms, 4)
            self._not_empty.notify()
            return True

    def dequeue(self, timeout: float = 0.2) -> Optional[QueuedEvent]:
        with self._not_empty:
            deadline = time.monotonic() + timeout
            while not self._q and not self.closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._not_empty.wait(timeout=remaining)
            if not self._q:
                return None
            item = self._q.popleft()
            self._bytes = max(0, self._bytes - item.estimated_bytes)
            self.metrics.dequeued += 1
            self.metrics.queue_current_events = len(self._q)
            self.metrics.queue_current_bytes = self._bytes
            lag_ms = (time.monotonic_ns() - item.enqueue_monotonic_ns) / 1_000_000.0
            self.metrics.writer_lag_ms_last = round(lag_ms, 3)
            if lag_ms > self.metrics.writer_lag_ms_max:
                self.metrics.writer_lag_ms_max = round(lag_ms, 3)
            return item

    def close(self) -> None:
        with self._not_empty:
            self.closed = True
            self._not_empty.notify_all()

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._q)
