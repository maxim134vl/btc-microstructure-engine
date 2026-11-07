"""Disk safety checks for fail-closed journal writes."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DiskStatus:
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_gb: float
    min_free_bytes: int
    is_low: bool
    estimated_bytes_per_second: Optional[float] = None
    estimated_gb_per_day: Optional[float] = None


def check_disk(path: Path | str, *, min_free_bytes: int) -> DiskStatus:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(target))
    free = int(usage.free)
    return DiskStatus(
        path=str(target.resolve()),
        total_bytes=int(usage.total),
        used_bytes=int(usage.used),
        free_bytes=free,
        free_gb=round(free / (1024**3), 3),
        min_free_bytes=int(min_free_bytes),
        is_low=free < int(min_free_bytes),
    )


def estimate_write_rate(
    *,
    bytes_written: int,
    duration_seconds: float,
) -> tuple[float, float]:
    if duration_seconds <= 0:
        return 0.0, 0.0
    bps = bytes_written / duration_seconds
    gb_day = (bps * 86400) / (1024**3)
    return bps, gb_day
