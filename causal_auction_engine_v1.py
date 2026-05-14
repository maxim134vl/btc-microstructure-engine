import pandas as pd
import numpy as np

print("\nCAUSAL AUCTION ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

path_df = pd.read_parquet(
    "auction_path_dependency_memory.parquet"
)

transitions_df = pd.read_parquet(
    "auction_state_transitions_memory.parquet"
)

liquidity_df = pd.read_parquet(
    "unified_liquidity_memory.parquet"
)

path_df = path_df.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

causal_states = []

# =====================================
# LOOP
# =====================================

for i in range(len(path_df)):

    row = path_df.iloc[i]

    timestamp = row["timestamp"]

    recent_transitions = transitions_df.loc[
        transitions_df["timestamp"] <= timestamp
    ].tail(10)

    recent_liquidity = liquidity_df.loc[
        liquidity_df["timestamp"] <= timestamp
    ].tail(10)

    # =====================================
    # COUNTERS
    # =====================================

    absorption_events = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "absorption"
        ]

    )

    initiative_events = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "initiative_participation"
        ]

    )

    balanced_events = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "balanced_participation"
        ]

    )

    no_demand_events = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "no_demand"
        ]

    )

    no_supply_events = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "no_supply"
        ]

    )

    failed_initiatives = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "initiative_failure"
        ]

    )

    # =====================================
    # DEFAULT
    # =====================================

    causal_condition = "undefined"

    causal_strength = 0

    # =====================================
    # ABSORPTION CAUSED REVERSAL
    # =====================================

    if (

        absorption_events >= 1

        and

        no_supply_events >= 1

        and

        row["markup_momentum"] > 0

    ):

        causal_condition = (
            "absorption_caused_reversal"
        )

        causal_strength = (

            absorption_events

            *

            row["markup_momentum"]

        )

    # =====================================
    # FAILED INITIATIVE CAUSED COMPRESSION
    # =====================================

    elif (

        failed_initiatives >= 1

        and

        row["compression_persistence"] > 0.15

    ):

        causal_condition = (
            "failed_initiative_caused_compression"
        )

        causal_strength = (

            failed_initiatives

            *

            row["compression_persistence"]

        )

    # =====================================
    # EXPANSION CAUSED EXHAUSTION
    # =====================================

    elif (

        row["expansion_persistence"] > 0.18

        and

        row["expansion_momentum"] < 0

    ):

        causal_condition = (
            "expansion_caused_exhaustion"
        )

        causal_strength = (

            row["expansion_persistence"]

            *

            abs(
                row["expansion_momentum"]
            )

        )

    # =====================================
    # TRAPPED PARTICIPATION
    # =====================================

    elif (

        initiative_events >= 3

        and

        failed_initiatives >= 1

    ):

        causal_condition = (
            "trapped_participation"
        )

        causal_strength = (

            initiative_events

            *

            failed_initiatives

        )

    # =====================================
    # DEFENDED LIQUIDITY CONTINUATION
    # =====================================

    elif (

        absorption_events >= 1

        and

        initiative_events >= 2

        and

        row["markup_persistence"] > 0.15

    ):

        causal_condition = (
            "defended_liquidity_continuation"
        )

        causal_strength = (

            absorption_events

            *

            row["markup_persistence"]

        )

    # =====================================
    # PASSIVE PULLBACK RECOVERY
    # =====================================

    elif (

        no_demand_events >= 2

        and

        initiative_events >= 1

        and

        row["markup_momentum"] > 0

    ):

        causal_condition = (
            "passive_pullback_recovery"
        )

        causal_strength = (

            no_demand_events

            *

            row["markup_momentum"]

        )

    # =====================================
    # SAVE
    # =====================================

    causal_row = {

        "timestamp": timestamp,

        "causal_condition": causal_condition,

        "causal_strength": causal_strength,

        "absorption_events": absorption_events,

        "initiative_events": initiative_events,

        "balanced_events": balanced_events,

        "no_demand_events": no_demand_events,

        "no_supply_events": no_supply_events,

        "failed_initiatives": failed_initiatives

    }

    causal_states.append(
        causal_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

causal_df = pd.DataFrame(
    causal_states
)

# =====================================
# SAVE MEMORY
# =====================================

causal_df.to_parquet(
    "causal_auction_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("CAUSAL AUCTION DEBUG")

print("=" * 50)

print()

print("CAUSAL CONDITIONS:")

print(

    causal_df["causal_condition"]

    .value_counts()

)

print()

print("LAST 30 CAUSAL STATES:")

debug_cols = [

    "causal_condition",

    "causal_strength",

    "absorption_events",

    "initiative_events",

    "balanced_events",

    "no_demand_events",

    "no_supply_events",

    "failed_initiatives"

]

print(

    causal_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "causal_auction_memory.parquet"
)

print()
