"""Shared parquet read safety helpers — temp detection and strict read errors."""

from __future__ import annotations


class ParquetReadError(OSError):
    """Raised when a finalized (non-temp) parquet cannot be read."""


def is_temp_parquet_path(path: str) -> bool:
    lowered = str(path).lower()
    return (
        lowered.endswith(".tmp")
        or ".parquet.tmp" in lowered
        or lowered.endswith(".part")
        or lowered.endswith(".lock")
    )
