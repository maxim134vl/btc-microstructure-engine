"""Timestamp helpers — UTC wall clock vs monotonic local order."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic_ns, time_ns
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ms_to_utc_iso(ms: Any) -> Optional[str]:
    """Convert exchange epoch milliseconds to UTC ISO-8601, or None if absent."""
    if ms is None:
        return None
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def capture_local_receive() -> tuple[str, int]:
    """Capture wall + monotonic receive stamps immediately on payload arrival."""
    wall_ns = time_ns()
    mono = monotonic_ns()
    dt = datetime.fromtimestamp(wall_ns / 1_000_000_000, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z"), mono
