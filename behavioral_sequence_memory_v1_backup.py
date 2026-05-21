import pandas as pd

from datetime import datetime

print()
print("BEHAVIORAL SEQUENCE MEMORY")
print()

# =====================================
# LOAD DATA
# =====================================

temporal = pd.read_parquet(
    "temporal_context_memory.parquet"
)

localization = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

reactions = pd.read_parquet(
    "volume_reactions.parquet"
)

events = pd.read_parquet(
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

# -------------------------------------

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

# -------------------------------------

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

# -------------------------------------

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

try:

    old = pd.read_parquet(
        "behavioral_sequence_memory.parquet"
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

except:

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
# MEMORY
# =====================================

row = pd.DataFrame([{

    "persistence":
        persistence,

    "timestamp":
        datetime.utcnow(),

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
# LOAD OLD MEMORY
# =====================================

try:

    old = pd.read_parquet(
        "behavioral_sequence_memory.parquet"
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

    row = pd.concat(
        [old, row]
    )

except:

    pass

    previous_sequence = (
        "NONE"
    )

    previous_persistence = 0

# =====================================
# SAVE
# =====================================

row.to_parquet(
    "behavioral_sequence_memory.parquet"
)

# =====================================
# OUTPUT
# =====================================

print(
    row.tail(10)
)

print()

print(
    "CURRENT SEQUENCE:"
)

print(
    sequence
)

print()
