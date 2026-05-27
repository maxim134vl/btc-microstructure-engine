import pandas as pd

from datetime import datetime

print()
print(
    "CLIMACTIC BEHAVIOR ENGINE"
)

# =====================================
# LOAD
# =====================================

response = pd.read_parquet(
    "volume_response_state.parquet"
)

# =====================================
# LATEST
# =====================================

latest = response.iloc[-1]

# =====================================
# VARIABLES
# =====================================

volume_class = (
    latest["volume_class"]
)

climax_state = (
    latest["climax_state"]
)

unfinished_auction = (
    latest["unfinished_auction"]
)

# =====================================
# MEMORY
# =====================================

recent = response.tail(20)

# =====================================
# COUNTS
# =====================================

climax_events = len(

    recent[
        recent["volume_class"]
        ==
        "climax"
    ]

)

# -------------------------------------

exhaustion_events = len(

    recent[
        recent["climax_state"]
        ==
        "CLIMAX_EXHAUSTION"
    ]

)

# -------------------------------------

continuation_events = len(

    recent[
        recent["climax_state"]
        ==
        "CLIMAX_CONTINUATION"
    ]

)

# -------------------------------------

absorption_events = len(

    recent[
        recent["climax_state"]
        ==
        "CLIMAX_ABSORPTION"
    ]

)

# =====================================
# INTERPRETATION
# =====================================

behavior_state = (
    "NEUTRAL_CLIMACTIC_BEHAVIOR"
)

# -------------------------------------

if exhaustion_events >= 2:

    behavior_state = (
        "REPEATED_EXHAUSTION"
    )

# -------------------------------------

elif continuation_events >= 2:

    behavior_state = (
        "INITIATIVE_CLIMAX"
    )

# -------------------------------------

elif absorption_events >= 2:

    behavior_state = (
        "ABSORPTIVE_CLIMAX"
    )

# -------------------------------------

elif climax_events >= 3:

    behavior_state = (
        "PERSISTENT_CLIMACTIC_ACTIVITY"
    )

# =====================================
# OUTPUT
# =====================================

print()

print(
    "CLIMACTIC STATE:"
)

print(
    behavior_state
)

print()

print(
    "CLIMAX EVENTS:"
)

print(
    climax_events
)

print()

print(
    "EXHAUSTION EVENTS:"
)

print(
    exhaustion_events
)

print()

print(
    "CONTINUATION EVENTS:"
)

print(
    continuation_events
)

print()

print(
    "ABSORPTION EVENTS:"
)

print(
    absorption_events
)

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "climactic_state":
        behavior_state,

    "climax_events":
        climax_events,

    "exhaustion_events":
        exhaustion_events,

    "continuation_events":
        continuation_events,

    "absorption_events":
        absorption_events,

    "unfinished_auction":
        unfinished_auction

}])

# -------------------------------------

try:

    old = pd.read_parquet(
        "climactic_behavior_memory.parquet"
    )

    row = pd.concat([
        old,
        row
    ])

except:

    pass

# -------------------------------------

row.to_parquet(
    "climactic_behavior_memory.parquet",
    index=False
)

print()
print(
    "MEMORY SAVED:"
)

print(
    "climactic_behavior_memory.parquet"
)

print()
