import pandas as pd
import numpy as np

print("\nAUCTION PATH DEPENDENCY ENGINE STARTED\n")

# =====================================
# LOAD MEMORIES
# =====================================

mtf = pd.read_parquet(
    "multi_timeframe_memory.parquet"
)

temporal = pd.read_parquet(
    "temporal_persistence_memory.parquet"
)

transitions = pd.read_parquet(
    "auction_state_transitions_memory.parquet"
)

mtf = mtf.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

path_states = []

# =====================================
# LOOP
# =====================================

for i in range(len(mtf)):

    row = mtf.iloc[i]

    timestamp = row["timestamp"]

    # =====================================
    # RECENT WINDOWS
    # =====================================

    recent_transitions = transitions.loc[
        transitions["timestamp"] <= timestamp
    ].tail(12)

    recent_temporal = temporal.loc[
        temporal["timestamp"] <= timestamp
    ].tail(12)

    # =====================================
    # COUNTERS
    # =====================================

    initiative_failures = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "initiative_failure"
        ]

    )

    passive_pullbacks = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "passive_pullback"
        ]

    )

    defended_absorptions = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "defended_absorption"
        ]

    )

    # =====================================
    # EXPANSION / COMPRESSION DRIFT
    # =====================================

    expansion_persistence = recent_temporal[
        "expansion_probability_persistence"
    ].mean()

    compression_persistence = recent_temporal[
        "compression_probability_persistence"
    ].mean()

    markup_persistence = recent_temporal[
        "markup_probability_persistence"
    ].mean()

    markdown_persistence = recent_temporal[
        "markdown_probability_persistence"
    ].mean()

    # =====================================
    # ACCELERATION
    # =====================================

    expansion_momentum = recent_temporal[
        "expansion_probability_momentum"
    ].mean()

    markup_momentum = recent_temporal[
        "markup_probability_momentum"
    ].mean()

    markdown_momentum = recent_temporal[
        "markdown_probability_momentum"
    ].mean()

    # =====================================
    # DEFAULT
    # =====================================

    market_condition = "undefined"

    path_strength = 0

    # =====================================
    # EXHAUSTED MARKUP
    # =====================================

    if (

        markup_persistence > 0.2

        and

        initiative_failures >= 1

        and

        expansion_momentum < 0

    ):

        market_condition = (
            "exhausted_markup"
        )

        path_strength = (

            markup_persistence

            *

            abs(expansion_momentum)

        )

    # =====================================
    # HEALTHY MARKUP
    # =====================================

    elif (

        markup_persistence > 0.2

        and

        passive_pullbacks >= 1

        and

        markup_momentum > 0

    ):

        market_condition = (
            "healthy_markup"
        )

        path_strength = (

            markup_persistence

            *

            markup_momentum

        )

    # =====================================
    # ACCUMULATION BUILDUP
    # =====================================

    elif (

        defended_absorptions >= 1

        and

        compression_persistence > 0.2

    ):

        market_condition = (
            "accumulation_buildup"
        )

        path_strength = (

            defended_absorptions

            *

            compression_persistence

        )

    # =====================================
    # LIQUIDITY EXPANSION
    # =====================================

    elif (

        expansion_persistence > 0.2

        and

        expansion_momentum > 0

    ):

        market_condition = (
            "aggressive_expansion"
        )

        path_strength = (

            expansion_persistence

            *

            expansion_momentum

        )

    # =====================================
    # TREND DECELERATION
    # =====================================

    elif (

        abs(markup_momentum) < 0.01

        and

        abs(markdown_momentum) < 0.01

        and

        compression_persistence > 0.15

    ):

        market_condition = (
            "trend_deceleration"
        )

        path_strength = compression_persistence

    # =====================================
    # DISTRIBUTION PRESSURE
    # =====================================

    elif (

        markdown_persistence > 0.2

        and

        initiative_failures >= 1

    ):

        market_condition = (
            "distribution_pressure"
        )

        path_strength = (

            markdown_persistence

            *

            initiative_failures

        )

    # =====================================
    # SAVE
    # =====================================

    path_row = {

        "timestamp": timestamp,

        "market_condition": market_condition,

        "path_strength": path_strength,

        "initiative_failures": initiative_failures,

        "passive_pullbacks": passive_pullbacks,

        "defended_absorptions": defended_absorptions,

        "markup_persistence": markup_persistence,

        "markdown_persistence": markdown_persistence,

        "compression_persistence": compression_persistence,

        "expansion_persistence": expansion_persistence,

        "markup_momentum": markup_momentum,

        "markdown_momentum": markdown_momentum,

        "expansion_momentum": expansion_momentum

    }

    path_states.append(
        path_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

path_df = pd.DataFrame(
    path_states
)

# =====================================
# SAVE MEMORY
# =====================================

path_df.to_parquet(
    "auction_path_dependency_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("PATH DEPENDENCY DEBUG")

print("=" * 50)

print()

print("MARKET CONDITIONS:")

print(

    path_df["market_condition"]

    .value_counts()

)

print()

print("LAST 30 PATH STATES:")

debug_cols = [

    "market_condition",

    "path_strength",

    "initiative_failures",

    "passive_pullbacks",

    "defended_absorptions",

    "markup_persistence",

    "markdown_persistence",

    "compression_persistence",

    "expansion_persistence",

    "markup_momentum",

    "markdown_momentum",

    "expansion_momentum"

]

print(

    path_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "auction_path_dependency_memory.parquet"
)

print()
