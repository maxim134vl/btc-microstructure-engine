import os

import pandas as pd

# Canonical live feed path (repository root, cwd-relative).
CANONICAL_LIVE_FEED_PATH = "live_market_feed.parquet"

# Deprecated compatibility path — kept in sync by writers.
LEGACY_LIVE_FEED_PATH = "datasets/live/latest.parquet"

LEGACY_PARTITION_DIR = "datasets/live"


def read_live_feed() -> pd.DataFrame:
    """Read canonical feed, migrating legacy snapshot if needed."""

    if os.path.exists(CANONICAL_LIVE_FEED_PATH):
        return pd.read_parquet(CANONICAL_LIVE_FEED_PATH)

    if os.path.exists(LEGACY_LIVE_FEED_PATH):
        legacy = pd.read_parquet(LEGACY_LIVE_FEED_PATH)
        write_live_feed_snapshot(legacy)
        return legacy

    return pd.DataFrame()


def write_live_feed_snapshot(df: pd.DataFrame) -> None:
    """Persist live feed to canonical path and legacy mirror."""

    os.makedirs(LEGACY_PARTITION_DIR, exist_ok=True)

    df.to_parquet(
        CANONICAL_LIVE_FEED_PATH,
        index=False,
    )

    df.to_parquet(
        LEGACY_LIVE_FEED_PATH,
        index=False,
    )
