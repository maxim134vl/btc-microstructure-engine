MAX_STATE_ROWS = 50000

import os

DEFAULT_DATASET_ROWS = 200000

RUNTIME_LOOP_DELAY = 5

STATE_DIRECTORY = "state"

DATASET_DIRECTORY = "datasets"

# Canonical live market feed (see storage/path_registry.py).
from storage.path_registry import (  # noqa: E402
    CANONICAL_LIVE_FEED_PATH,
    LEGACY_LIVE_FEED_PATH as LEGACY_LIVE_FEED_PARQUET,
)

LIVE_MARKET_FEED_PARQUET = CANONICAL_LIVE_FEED_PATH

ENABLE_RUNTIME_CACHE = True

ENABLE_EVENT_DRIVEN = True

# Engine execution hardening (Phase operational)
ENGINE_TIMEOUT_SECONDS = int(os.environ.get("ENGINE_TIMEOUT_SECONDS", "120"))
ENGINE_KILL_GRACE_SECONDS = int(os.environ.get("ENGINE_KILL_GRACE_SECONDS", "5"))
STALL_DETECTION_SECONDS = int(os.environ.get("STALL_DETECTION_SECONDS", "180"))
