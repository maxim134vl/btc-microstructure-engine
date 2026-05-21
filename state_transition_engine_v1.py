import os
from runtime_cache import (
    load_parquet_cached
)

import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

import os

from datetime import datetime

print()
print(
    "STATE TRANSITION ENGINE"
)

MEMORY_FILE = (
    "state_transition_memory.parquet"
)

MAX_ROWS = 50000

STATE_FILE = (
    "state_transition_engine_state.parquet"
)

# =====================================
# LOAD
# =====================================

synthesis = load_parquet_cached(
    "auction_synthesis_memory.parquet"
)

probabilistic = load_parquet_cached(
    "probabilistic_auction_memory.parquet"
)

try:

    previous_state = safe_read_parquet(
        STATE_FILE
    )

    previous_dependency_state = (
        previous_state.iloc[-1][
            "dependency_state"
        ]
    )

    if (

        previous_dependency_state

        ==

        current_dependency_state

    ):

        print()

        print(
            "NO UPSTREAM STATE CHANGE"
        )

        quit()

except Exception:

    pass

# =====================================
# RECENT STATES
# =====================================

recent_synthesis = synthesis.tail(2)

recent_probabilistic = probabilistic.tail(2)

if len(recent_synthesis) < 2:

    print()

    print(
        "WAITING FOR SECOND STATE"
    )

    quit()

if len(recent_probabilistic) < 2:

    print()

    print(
        "WAITING FOR SECOND REGIME"
    )

    quit()

current_dependency_state = str(

    recent_synthesis.iloc[-1][
        "auction_state"
    ]

) + str(

    recent_probabilistic.iloc[-1][
        "auction_regime"
    ]

)

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

if previous_state != current_state:

    transition_state = (
        "AUCTION_STATE_TRANSITION"
    )

if previous_regime != current_regime:

    transition_state = (
        "REGIME_TRANSITION"
    )

if (

    previous_state != current_state

    and

    previous_regime != current_regime

):

    transition_state = (
        "FULL_COGNITIVE_TRANSITION"
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
# NEW ROW
# =====================================

new_row = pd.DataFrame([{

    "timestamp":
        pd.Timestamp.now().tz_localize(None),

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

append_state_row(

    MEMORY_FILE,

    new_row

)

# =====================================
# OUTPUT
# =====================================

print()

print(
    "MEMORY SAVED:"
)

print(
    MEMORY_FILE
)

dependency_state = pd.DataFrame([{

    "timestamp":
        pd.Timestamp.now().tz_localize(None),

    "dependency_state":
        current_dependency_state

}])

append_state_row(

    STATE_FILE,

    dependency_state,

    max_rows=1

)

print()
