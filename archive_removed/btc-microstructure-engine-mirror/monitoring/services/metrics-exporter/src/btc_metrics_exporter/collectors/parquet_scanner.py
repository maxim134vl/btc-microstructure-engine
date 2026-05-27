"""
Filesystem-level observability for the parquet store.

We do not read full files — for size we `stat()`, for row count and schema
we use parquet metadata-only reads (cheap: just the footer). Tail sample
reads happen in feature_health, scoped to known feature columns.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow.parquet as pq

from ..config import EXPECTED_COLUMNS
from .base import Collector

if TYPE_CHECKING:
    pass


HISTORY_LIMIT = 60   # samples per file (~10 minutes at 10s scan interval)


class ParquetScannerCollector(Collector):
    """Per-file freshness, size, row count, growth rate, schema validity."""

    name = "parquet_scanner"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # remember (rows, mtime) per file to compute deltas across ticks
        self._prev: dict[str, tuple[int, float]] = {}
        # ring buffer of (unix_ts, rows) per file, surfaced via state["history"]
        self.state.setdefault("history", {})

    async def collect(self) -> None:
        data_dir: Path = self.cfg.data_dir
        if not data_dir.is_dir():
            self.log.warning("data_dir.missing", path=str(data_dir))
            return

        now = time.time()
        # discover parquet files (non-recursive — runtime writes flat into /data)
        files = sorted(data_dir.glob("*.parquet"))
        if not files:
            self.log.info("no_parquet_found", path=str(data_dir))

        # offload blocking stat/parquet calls to threadpool
        await asyncio.gather(*(self._scan_one(p, now) for p in files))

    async def _scan_one(self, path: Path, now: float) -> None:
        loop = asyncio.get_running_loop()
        basename = path.name
        try:
            stat = await loop.run_in_executor(None, path.stat)
        except FileNotFoundError:
            # raced with another writer; skip this tick
            return
        except OSError as e:
            self.metrics.parquet_read_errors_total.labels(basename, "stat").inc()
            self.log.warning("stat.failed", file=basename, err=str(e))
            return

        # always emit size + age
        self.metrics.parquet_size_bytes.labels(basename).set(stat.st_size)
        self.metrics.parquet_age_seconds.labels(basename).set(max(0.0, now - stat.st_mtime))

        # try to read metadata for row count + schema
        try:
            meta = await loop.run_in_executor(None, _read_metadata, path)
        except Exception as e:
            self.metrics.parquet_read_errors_total.labels(basename, "metadata").inc()
            self.log.warning("metadata.failed", file=basename, err=str(e))
            # schema cannot be verified — emit 0 so it's visible
            self.metrics.parquet_schema_valid.labels(basename).set(0)
            return

        rows, columns = meta
        self.metrics.parquet_rows_total.labels(basename).set(rows)

        # schema check (only for files in the allowlist)
        expected = EXPECTED_COLUMNS.get(basename)
        if expected is None:
            self.metrics.parquet_schema_valid.labels(basename).set(1)
        else:
            ok = expected.issubset(columns)
            self.metrics.parquet_schema_valid.labels(basename).set(1 if ok else 0)
            if not ok:
                self.log.warning(
                    "schema.invalid",
                    file=basename,
                    expected=sorted(expected),
                    missing=sorted(expected - columns),
                )

        # row delta per minute (compared to the previous tick)
        prev = self._prev.get(basename)
        if prev is not None:
            prev_rows, prev_ts = prev
            dt = now - prev_ts
            if dt > 0:
                rate = max(0, rows - prev_rows) * 60.0 / dt
                self.metrics.parquet_rows_delta_per_minute.labels(basename).set(rate)
        self._prev[basename] = (rows, now)

        # append (ts, rows) to ring buffer
        hist = self.state["history"].setdefault(basename, [])
        hist.append([int(now), int(rows)])
        if len(hist) > HISTORY_LIMIT:
            del hist[: len(hist) - HISTORY_LIMIT]


def _read_metadata(path: Path) -> tuple[int, set[str]]:
    """Read row count + column names without loading the data. O(file footer)."""
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    return pf.metadata.num_rows, set(schema.names)
