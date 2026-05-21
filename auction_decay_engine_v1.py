import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from datetime import datetime

print()
print(
    "AUCTION DECAY ENGINE"
)

# =====================================
# LOAD
# =====================================

convergence = safe_read_parquet(
    "auction_convergence_memory.parquet"
)

reinforcement = safe_read_parquet(
    "auction_reinforcement_memory.parquet"
)

# =====================================
# LATEST
# =====================================

latest_convergence = (
    convergence.iloc[-1]
)

latest_reinforcement = (
    reinforcement.iloc[-1]
)

# =====================================
# VARIABLES
# =====================================

recent_convergence = (
    convergence.tail(20)
)

# =====================================
# MEMORY PRESSURE
# =====================================

distribution_events = len(

    recent_convergence[

        recent_convergence[
            "localized_behavior"
        ]

        ==

        "localized_distribution"

    ]

)

# -------------------------------------

unfinished_auctions = len(

    recent_convergence[

        recent_convergence[
            "unfinished_auction"
        ]

        ==

        True

    ]

)

# -------------------------------------

belief_strength = float(

    latest_reinforcement[
        "belief_strength"
    ]

)

# =====================================
# DECAY
# =====================================

distribution_decay = (
    distribution_events * 0.95
)

unfinished_decay = (
    unfinished_auctions * 0.95
)

belief_decay = (
    belief_strength * 0.97
)

# =====================================
# RESET CONDITIONS
# =====================================

reset_state = (
    "NO_RESET"
)

# -------------------------------------

if belief_decay < 0.2:

    reset_state = (
        "LOW_CONVICTION_RESET"
    )

# -------------------------------------

if distribution_decay < 1:

    reset_state = (
        "DISTRIBUTION_MEMORY_RESET"
    )

# -------------------------------------

if unfinished_decay < 1:

    reset_state = (
        "AUCTION_RESOLUTION_RESET"
    )

# =====================================
# OUTPUT
# =====================================

print()

print(
    "RESET STATE:"
)

print(
    reset_state
)

print()

print(
    "DISTRIBUTION DECAY:"
)

print(
    round(
        distribution_decay,
        2
    )
)

print()

print(
    "UNFINISHED AUCTION DECAY:"
)

print(
    round(
        unfinished_decay,
        2
    )
)

print()

print(
    "BELIEF DECAY:"
)

print(
    round(
        belief_decay,
        2
    )
)

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "reset_state":
        reset_state,

    "distribution_decay":
        distribution_decay,

    "unfinished_decay":
        unfinished_decay,

    "belief_decay":
        belief_decay

}])

append_state_row(

    "auction_decay_memory.parquet",

    row

)

print()

print(
    "MEMORY SAVED:"
)

print(
    "auction_decay_memory.parquet"
)

print()
