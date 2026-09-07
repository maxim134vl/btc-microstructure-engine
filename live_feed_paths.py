import os
from pathlib import Path

import pandas as pd

from storage.path_registry import (
    CANONICAL_LIVE_FEED_PATH,
    LEGACY_LIVE_FEED_PATH,
    data_root,
    resolve_read,
    resolve_write,
)

# Writable under data/ (Docker/VPS root FS is read-only). Keep datasets/live as
# a read-only fallback for host/legacy installs that still have partitions there.
LEGACY_PARTITION_DIR = str(data_root() / "live" / "partitions")
_HOST_LEGACY_PARTITION_DIR = "datasets/live"
_CANONICAL_LEGACY_MIRROR = str(data_root() / "live" / "latest.parquet")

# Backward-compatible exports (Phase 4B — canonical paths via registry).
__all__ = [
    "CANONICAL_LIVE_FEED_PATH",
    "LEGACY_LIVE_FEED_PATH",
    "LEGACY_PARTITION_DIR",
    "read_live_feed",
    "read_live_feed_history",
    "write_live_feed_snapshot",
]


def read_live_feed() -> pd.DataFrame:
    """Read canonical feed, migrating legacy snapshot if needed."""

    path = resolve_read(CANONICAL_LIVE_FEED_PATH)
    if os.path.exists(path):
        return pd.read_parquet(path)

    return pd.DataFrame()


def _iter_partition_dirs() -> list[Path]:
    dirs: list[Path] = []
    for raw in (LEGACY_PARTITION_DIR, _HOST_LEGACY_PARTITION_DIR):
        path = Path(raw)
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def read_live_feed_history() -> pd.DataFrame:
    """Merge daily partition files and the canonical snapshot into one timeline."""

    frames: list[pd.DataFrame] = []
    for partition_dir in _iter_partition_dirs():
        for path in sorted(partition_dir.glob("*.parquet")):
            if path.name == "latest.parquet":
                continue
            try:
                frames.append(pd.read_parquet(path))
            except Exception:
                continue

    snapshot = read_live_feed()
    if len(snapshot) > 0:
        frames.append(snapshot)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return (
        df.drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def write_live_feed_snapshot(df: pd.DataFrame) -> None:
    """Persist live feed to canonical path and best-effort legacy mirrors."""

    canonical = resolve_write(CANONICAL_LIVE_FEED_PATH)
    os.makedirs(LEGACY_PARTITION_DIR, exist_ok=True)

    df.to_parquet(
        canonical,
        index=False,
    )

    # Prefer writable data/ mirror; fall back to datasets/ only when possible.
    for mirror in (_CANONICAL_LEGACY_MIRROR, LEGACY_LIVE_FEED_PATH):
        try:
            parent = os.path.dirname(mirror)
            if parent:
                os.makedirs(parent, exist_ok=True)
            df.to_parquet(mirror, index=False)
            break
        except OSError:
            continue
