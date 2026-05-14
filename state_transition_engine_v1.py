import pandas as pd

from datetime import datetime

print()
print(
    "STATE TRANSITION ENGINE"
)

# =====================================
# LOAD
# =====================================

synthesis = pd.read_parquet(
    "auction_synthesis_memory.parquet"
)

probabilistic = pd.read_parquet(
    "probabilistic_auction_memory.parquet"
)

# =====================================
# RECENT STATES
# =====================================

recent_synthesis = (
    synthesis.tail(2)
)

recent_probabilistic = (
    probabilistic.tail(2)
)

# =====================================
# SAFETY
# =====================================

if len(recent_synthesis) < 2:

    print()
    print(
        "NOT ENOUGH STATE HISTORY"
    )

    quit()

# =====================================
# PREVIOUS / CURRENT
# =====================================

previous_state = (
    recent_synthesis.iloc[-2][
        "auction_state"
    ]
)

current_state = (
    recent_synthesis.iloc[-1][
        "auction_state"
    ]
)

# -------------------------------------

previous_regime = (
    recent_probabilistic.iloc[-2][
        "auction_regime"
    ]
)

current_regime = (
    recent_probabilistic.iloc[-1][
        "auction_regime"
    ]
)

# =====================================
# TRANSITION
# =====================================

transition_state = (
    "STABLE_STATE"
)

# -------------------------------------

if previous_state != current_state:

    transition_state = (
        "AUCTION_STATE_TRANSITION"
    )

# -------------------------------------

if previous_regime != current_regime:

    transition_state = (
        "REGIME_TRANSITION"
    )

# -------------------------------------

if (

    previous_state != current_state

    and

    previous_regime != current_regime

):

    transition_state = (
        "FULL_COGNITIVE_TRANSITION"
    )

# =====================================
# INTERPRETATION MEMORY
# =====================================

interpretation = (
    current_state
)

# =====================================
# OUTPUT
# =====================================

print()

print(
    "PREVIOUS STATE:"
)

print(
    previous_state
)

print()

print(
    "CURRENT STATE:"
)

print(
    current_state
)

print()

print(
    "PREVIOUS REGIME:"
)

print(
    previous_regime
)

print()

print(
    "CURRENT REGIME:"
)

print(
    current_regime
)

print()

print(
    "TRANSITION STATE:"
)

print(
    transition_state
)

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "previous_state":
        previous_state,

    "current_state":
        current_state,

    "previous_regime":
        previous_regime,

    "current_regime":
        current_regime,

    "transition_state":
        transition_state

}])

# -------------------------------------

try:

    old = pd.read_parquet(
        "state_transition_memory.parquet"
    )

    row = pd.concat([
        old,
        row
    ])

except:

    pass

# -------------------------------------

row.to_parquet(
    "state_transition_memory.parquet",
    index=False
)

print()
print(
    "MEMORY SAVED:"
)

print(
    "state_transition_memory.parquet"
)

print()
