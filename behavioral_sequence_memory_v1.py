from runtime_cache import (
    load_parquet_cached
)

import pandas as pd
import os

from datetime import datetime
from storage.path_registry import resolve_write

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

temporal = load_parquet_cached(
    "temporal_context_memory.parquet"
)

localization = load_parquet_cached(
    "volume_localization_v2_memory.parquet"
)

reactions = load_parquet_cached(
    "volume_reactions.parquet"
)

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

try:

    old = load_parquet_cached(
        MEMORY_FILE
    )

    previous_sequence = (
        old.iloc[-1][
            "sequence"
        ]
    )

    previous_persistence = (
        old.iloc[-1][
            "persistence"
        ]
    )

except Exception:

    old = pd.DataFrame()

    previous_sequence = (
        "NONE"
    )

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

    "sequence":
        sequence,

    "event_state":
        event_state,

    "localized_behavior":
        localized_behavior,

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
