"""Research-only volume localization shadow producer (Phase 3)."""

from .producer import (
    ALGORITHM_VERSION,
    SOURCE_TIMEFRAME,
    build_shadow_frame,
    run_shadow_once,
    watch_natural_bars,
)

__all__ = [
    "ALGORITHM_VERSION",
    "SOURCE_TIMEFRAME",
    "build_shadow_frame",
    "run_shadow_once",
    "watch_natural_bars",
]
