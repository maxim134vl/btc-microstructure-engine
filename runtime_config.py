MAX_STATE_ROWS = 50000

DEFAULT_DATASET_ROWS = 200000

RUNTIME_LOOP_DELAY = 5

STATE_DIRECTORY = "state"

DATASET_DIRECTORY = "datasets"

# Canonical live market feed (see live_feed_paths.py).
LIVE_MARKET_FEED_PARQUET = "live_market_feed.parquet"

# Deprecated mirror path — kept in sync for backward compatibility.
LEGACY_LIVE_FEED_PARQUET = "datasets/live/latest.parquet"

ENABLE_RUNTIME_CACHE = True

ENABLE_EVENT_DRIVEN = True
