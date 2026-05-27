import os

import pandas as pd

from storage.path_registry import (
    CANONICAL_LIVE_FEED_PATH,
    LEGACY_LIVE_FEED_PATH,
    resolve_read,
    resolve_write,
)

LEGACY_PARTITION_DIR = "datasets/live"

# Backward-compatible exports (Phase 4B — canonical paths via registry).
__all__ = [
    "CANONICAL_LIVE_FEED_PATH",
    "LEGACY_LIVE_FEED_PATH",
    "LEGACY_PARTITION_DIR",
    "read_live_feed",
    "write_live_feed_snapshot",
]


def read_live_feed() -> pd.DataFrame:
    """Read canonical feed, migrating legacy snapshot if needed."""

    path = resolve_read(CANONICAL_LIVE_FEED_PATH)
    if os.path.exists(path):
        return pd.read_parquet(path)

    return pd.DataFrame()


def write_live_feed_snapshot(df: pd.DataFrame) -> None:
    """Persist live feed to canonical path and legacy mirror (no silent duplication)."""

    canonical = resolve_write(CANONICAL_LIVE_FEED_PATH)
    os.makedirs(LEGACY_PARTITION_DIR, exist_ok=True)

    df.to_parquet(
        canonical,
        index=False,
    )

    df.to_parquet(
        LEGACY_LIVE_FEED_PATH,
        index=False,
    )
