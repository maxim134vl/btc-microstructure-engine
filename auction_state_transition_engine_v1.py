import pandas as pd
import numpy as np

print("\nAUCTION STATE TRANSITION ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "unified_liquidity_memory.parquet"
)

df = df.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

transitions = []

# =====================================
# LOOP
# =====================================

for i in range(1, len(df)):

    current = df.iloc[i]

    previous = df.iloc[i - 1]

    current_time = current["timestamp"]

    previous_time = previous["timestamp"]

    previous_behavior = previous["behavior"]

    current_behavior = current["behavior"]

    # =====================================
    # DEFAULT
    # =====================================

    transition_type = "undefined"

    transition_strength = 0

    # =====================================
    # INITIATIVE CONTINUATION
    # =====================================

    if (

        previous_behavior

        ==

        "initiative_participation"

        and

        current_behavior

        ==

        "initiative_participation"

    ):

        transition_type = (
            "initiative_continuation"
        )

        transition_strength = (

            current["participation_score"]

            *

            current["directional_score"]

        )

    # =====================================
    # PASSIVE PULLBACK
    # =====================================

    elif (

        previous_behavior

        ==

        "initiative_participation"

        and

        current_behavior

        in [

            "no_supply",

            "no_demand"

        ]

    ):

        transition_type = (
            "passive_pullback"
        )

        transition_strength = (

            abs(

                current[
                    "trend_pressure_score"
                ]

            )

            /

            (

                current[
                    "participation_score"
                ]

                +

                0.000001

            )

        )

    # =====================================
    # ABSORPTION DEFENSE
    # =====================================

    elif (

        previous_behavior

        ==

        "absorption"

        and

        current_behavior

        in [

            "balanced_participation",

            "initiative_participation"

        ]

    ):

        transition_type = (
            "defended_absorption"
        )

        transition_strength = (

            current[
                "close"
            ]

            -

            previous[
                "close"
            ]

        )

    # =====================================
    # FAILED INITIATIVE
    # =====================================

    elif (

        previous_behavior

        ==

        "initiative_participation"

        and

        current_behavior

        ==

        "absorption"

    ):

        transition_type = (
            "initiative_failure"
        )

        transition_strength = (

            current[
                "imbalance_score"
            ]

        )

    # =====================================
    # BALANCED AUCTION
    # =====================================

    elif (

        previous_behavior

        ==

        "balanced_participation"

        and

        current_behavior

        ==

        "balanced_participation"

    ):

        transition_type = (
            "balanced_auction"
        )

        transition_strength = (

            current[
                "spread_score"
            ]

        )

    # =====================================
    # SAVE TRANSITION
    # =====================================

    transition = {

        "timestamp": current_time,

        "previous_behavior": previous_behavior,

        "current_behavior": current_behavior,

        "transition_type": transition_type,

        "transition_strength": transition_strength,

        "previous_close": previous["close"],

        "current_close": current["close"],

        "price_change": (

            current["close"]

            -

            previous["close"]

        )

    }

    transitions.append(
        transition
    )

# =====================================
# BUILD DATAFRAME
# =====================================

transitions_df = pd.DataFrame(
    transitions
)

# =====================================
# SAVE MEMORY
# =====================================

transitions_df.to_parquet(
    "auction_state_transitions_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("AUCTION TRANSITIONS DEBUG")

print("=" * 50)

print()

print("TRANSITION DISTRIBUTION:")

print(

    transitions_df["transition_type"]

    .value_counts()

)

print()

print("LAST 30 TRANSITIONS:")

debug_cols = [

    "previous_behavior",

    "current_behavior",

    "transition_type",

    "transition_strength",

    "price_change"

]

print(

    transitions_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "auction_state_transitions_memory.parquet"
)

print()
