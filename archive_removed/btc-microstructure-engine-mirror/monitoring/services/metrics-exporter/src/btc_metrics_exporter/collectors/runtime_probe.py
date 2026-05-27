"""
Derive a runtime liveness signal without modifying engine code.

Strategy: take the minimum age (newest mtime) across the parquet files
the runtime is expected to write. If the runtime is alive, *something*
is being touched. We don't claim this is perfect — a stuck producer
could still update mtime without making progress — but the collectors
that write are short-lived processes, so a stale mtime really does
indicate "nothing is being produced."

Better signal (v0.2): have autonomous_runtime_v2.py write a heartbeat
file we can probe directly. The probe code already handles both paths.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..config import EXPECTED_COLUMNS
from .base import Collector

RUNTIME_NAME = "autonomous_runtime_v2"
HEARTBEAT_FILE = "runtime_heartbeat"   # optional; runtime may write this


class RuntimeProbeCollector(Collector):
    name = "runtime_probe"

    async def collect(self) -> None:
        data_dir: Path = self.cfg.data_dir
        if not data_dir.is_dir():
            return

        # heartbeat file wins if present
        hb = data_dir / HEARTBEAT_FILE
        if hb.is_file():
            try:
                age = time.time() - hb.stat().st_mtime
                self.metrics.runtime_last_iter_age_seconds.labels(RUNTIME_NAME).set(max(0.0, age))
                return
            except OSError:
                pass

        # fallback: min age across known parquet outputs
        ages: list[float] = []
        now = time.time()
        for basename in EXPECTED_COLUMNS:
            path = data_dir / basename
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            except OSError:
                continue
            ages.append(max(0.0, now - mtime))

        if not ages:
            # nothing produced yet — emit a deliberately large value so
            # the alert fires (runtime is effectively stalled until first write)
            self.metrics.runtime_last_iter_age_seconds.labels(RUNTIME_NAME).set(999999.0)
            return

        self.metrics.runtime_last_iter_age_seconds.labels(RUNTIME_NAME).set(min(ages))
