"""
Collector interface. Each tick the runner calls `collect()` on every
registered collector. Errors are caught here, counted, and logged — a
single collector failure must not stop neighbors.
"""

from __future__ import annotations

import abc
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..registry import Metrics
    from structlog.stdlib import BoundLogger


class Collector(abc.ABC):
    """Abstract base for telemetry collectors."""

    name: str = "base"

    def __init__(self, cfg: "Config", metrics: "Metrics", log: "BoundLogger",
                 state: dict | None = None) -> None:
        self.cfg = cfg
        self.metrics = metrics
        self.log = log.bind(collector=self.name)
        # Shared mutable state for cross-collector / server-side reads
        # (e.g. ring-buffered history surfaced via /api/history/rows).
        self.state = state if state is not None else {}

    @abc.abstractmethod
    async def collect(self) -> None:
        """Perform one scan. May read filesystem / parquet; must not block long."""

    async def safe_collect(self) -> None:
        """Wrapper that times the scan, counts errors, never raises."""
        m = self.metrics
        start = time.perf_counter()
        try:
            await self.collect()
            m.exporter_scans_total.labels(self.name).inc()
        except Exception:
            m.exporter_scan_errors_total.labels(self.name).inc()
            self.log.exception("collector.error")
        finally:
            m.exporter_scan_duration_seconds.labels(self.name).set(
                time.perf_counter() - start
            )
