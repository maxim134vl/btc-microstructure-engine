from runtime_cache import (
    load_parquet_cached
)

import pandas as pd
import os

from datetime import datetime
from storage.path_registry import resolve_write, data_root
from btc_ml.runtime.cognitive_cycle import committed_paths
_cognitive_paths = committed_paths(data_root())

from legacy_source_inputs import read_consumer_source
_legacy_available_at = pd.Timestamp.now(tz="UTC")

print()
print("BEHAVIORAL SEQUENCE MEMORY")
print()

MEMORY_FILE = (
    "behavioral_sequence_memory.parquet"
)

MAX_ROWS = 50000

# =====================================
# LOAD DATA
# =====================================

temporal = pd.read_parquet(_cognitive_paths["temporal_context_memory.parquet"])

localization = pd.read_parquet(_cognitive_paths["volume_localization_v2_memory.parquet"])

# Original published source was qualified at the cycle cutoff; pin that exact input.
reactions = pd.read_parquet(_cognitive_paths['volume_reactions.parquet'])

events = load_parquet_cached(
    "behavioral_events_memory.parquet"
)

# =====================================
# LATEST STATES
# =====================================

latest_temporal = (
    temporal.iloc[-1]
)

latest_localization = (
    localization.iloc[-1]
)

latest_reaction = (
    reactions.iloc[-1]
)

latest_event = (
    events.iloc[-1]
)

# =====================================
# EXTRACT
# =====================================

event_state = (
    latest_temporal[
        "event_state"
    ]
)

localized_behavior = (
    latest_localization[
        "behavior"
    ]
)

delta_efficiency = (
    latest_reaction[
        "delta_efficiency"
    ]
)

delta = (
    latest_reaction[
        "delta"
    ]
)

behavioral_event = (
    latest_event[
        "event_type"
    ]
)

# =====================================
# DETECT SEQUENCES
# =====================================

sequence = (
    "NEUTRAL"
)

if (

    localized_behavior
    ==
    "localized_distribution"

    and

    abs(delta_efficiency) < 0.3

):

    sequence = (
        "FAILED_CONTINUATION_SEQUENCE"
    )

if (

    behavioral_event
    ==
    "stopping"

    and

    abs(delta) < 15

):

    sequence = (
        "EXHAUSTION_SEQUENCE"
    )

if (

    localized_behavior
    ==
    "localized_absorption"

    and

    abs(delta_efficiency) < 0.5

):

    sequence = (
        "ABSORPTION_SEQUENCE"
    )

# =====================================
# LOAD PREVIOUS STATE
# =====================================

# Use the market-observation timestamp from the verified Temporal commit,
# never the wall-clock time of this consumer process, as the identity key.
observation_timestamp = pd.to_datetime(
    latest_temporal["timestamp"], utc=True, errors="raise"
)
if pd.isna(observation_timestamp):
    raise RuntimeError("BEHAVIORAL_OBSERVATION_TIMESTAMP_INVALID")

from storage.path_registry import resolve_read
try:
    # Read durable storage, not a short-lived cached copy, before idempotence.
    old = pd.read_parquet(resolve_read(MEMORY_FILE))
except FileNotFoundError:
    old = pd.DataFrame()

if len(old) > 0:
    required = {"observation_timestamp", "sequence", "persistence",
                "event_state", "localized_behavior", "behavioral_event",
                "delta_efficiency", "delta"}
    if not required.issubset(old.columns):
        raise RuntimeError("BEHAVIORAL_HISTORY_REQUIRES_EXPLICIT_MIGRATION")
    historic_keys = pd.to_datetime(
        old["observation_timestamp"], utc=True, errors="raise"
    )
    if historic_keys.isna().any() or historic_keys.duplicated().any() or not historic_keys.is_monotonic_increasing:
        raise RuntimeError("BEHAVIORAL_HISTORY_IDENTITY_INTEGRITY_ERROR")
    previous_sequence = old.iloc[-1]["sequence"]
    previous_persistence = old.iloc[-1]["persistence"]
    if observation_timestamp < historic_keys.iloc[-1]:
        raise RuntimeError("BEHAVIORAL_OUT_OF_ORDER_OBSERVATION")
    if observation_timestamp == historic_keys.iloc[-1]:
        current_values = {
            "sequence": sequence,
            "event_state": event_state,
            "localized_behavior": localized_behavior,
            "behavioral_event": behavioral_event,
            "delta_efficiency": delta_efficiency,
            "delta": delta,
        }
        if any(old.iloc[-1][key] != value for key, value in current_values.items()):
            raise RuntimeError("BEHAVIORAL_OBSERVATION_COLLISION_CHANGED_INPUTS")
        print("BEHAVIORAL_OBSERVATION_ALREADY_PROCESSED:", observation_timestamp)
        raise SystemExit(0)
else:
    previous_sequence = "NONE"
    previous_persistence = 0

# =====================================
# PERSISTENCE
# =====================================

if sequence == previous_sequence:

    persistence = (
        previous_persistence + 1
    )

else:

    persistence = 1

# =====================================
# NEW ROW
# =====================================

new_row = pd.DataFrame([{

    "persistence":
        persistence,

    "timestamp":
        pd.Timestamp.now().tz_localize(None),

    "observation_timestamp":
        observation_timestamp.tz_convert(None),

    "sequence":
        sequence,

    "event_state":
        event_state,

    "localized_behavior":
        localized_behavior,

    "behavioral_event":
        behavioral_event,

    "delta_efficiency":
        delta_efficiency,

    "delta":
        delta

}])

# =====================================
# APPEND ONLY
# =====================================

combined = pd.concat(

    [old, new_row],

    ignore_index=True

)

# =====================================
# CLEANUP
# =====================================

combined = combined.drop_duplicates(
    subset=["timestamp"]
)

# =====================================
# LIMIT
# =====================================

if len(combined) > MAX_ROWS:

    combined = combined.iloc[
        -MAX_ROWS:
    ]

# =====================================
# ATOMIC WRITE
# =====================================

temp_file = (
    resolve_write(MEMORY_FILE) + ".tmp"
)

combined.to_parquet(
    temp_file,
    index=False
)

os.replace(
    temp_file,
    resolve_write(MEMORY_FILE)
)

# =====================================
# OUTPUT
# =====================================

print(
    "SEQUENCE:",
    sequence
)

print(
    "PERSISTENCE:",
    persistence
)
