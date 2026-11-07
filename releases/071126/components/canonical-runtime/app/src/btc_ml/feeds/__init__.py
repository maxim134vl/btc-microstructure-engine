"""Feed integration shims."""

try:
    from live_feed_paths import CANONICAL_LIVE_FEED_PATH, LEGACY_LIVE_FEED_PATH
except ModuleNotFoundError:  # pragma: no cover - src-only import path
    # Allow importing subpackages (e.g. raw_event_journal) when only `src/` is on sys.path.
    CANONICAL_LIVE_FEED_PATH = None
    LEGACY_LIVE_FEED_PATH = None

__all__ = ["CANONICAL_LIVE_FEED_PATH", "LEGACY_LIVE_FEED_PATH"]
