import pandas as pd
import numpy as np

print("\nINTENT INFERENCE ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

causal_df = pd.read_parquet(
    "causal_auction_memory.parquet"
)

path_df = pd.read_parquet(
    "auction_path_dependency_memory.parquet"
)

mtf_df = pd.read_parquet(
    "multi_timeframe_memory.parquet"
)

liquidity_df = pd.read_parquet(
    "unified_liquidity_memory.parquet"
)

# =====================================
# CLEAN
# =====================================

causal_df = causal_df.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

intent_states = []

# =====================================
# LOOP
# =====================================

for i in range(len(causal_df)):

    causal_row = causal_df.iloc[i]

    timestamp = causal_row["timestamp"]

    # =====================================
    # RECENT CONTEXT
    # =====================================

    recent_liquidity = liquidity_df.loc[
        liquidity_df["timestamp"] <= timestamp
    ].tail(12)

    recent_path = path_df.loc[
        path_df["timestamp"] <= timestamp
    ].tail(12)

    recent_mtf = mtf_df.loc[
        mtf_df["timestamp"] <= timestamp
    ].tail(12)

    # =====================================
    # COUNTERS
    # =====================================

    absorption_count = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "absorption"
        ]

    )

    initiative_count = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "initiative_participation"
        ]

    )

    no_demand_count = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "no_demand"
        ]

    )

    no_supply_count = len(

        recent_liquidity.loc[
            recent_liquidity[
                "behavior"
            ] == "no_supply"
        ]

    )

    conflict_count = len(

        recent_mtf.loc[
            recent_mtf[
                "conflict"
            ] == True
        ]

    )

    aligned_count = len(

        recent_mtf.loc[
            recent_mtf[
                "aligned"
            ] == True
        ]

    )

    # =====================================
    # MOMENTUMS
    # =====================================

    latest_path = recent_path.iloc[-1]

    markup_momentum = latest_path[
        "markup_momentum"
    ]

    markdown_momentum = latest_path[
        "markdown_momentum"
    ]

    expansion_momentum = latest_path[
        "expansion_momentum"
    ]

    # =====================================
    # DEFAULT
    # =====================================

    inferred_intent = "undefined"

    intent_strength = 0

    # =====================================
    # CONTINUATION INTENT
    # =====================================

    if (

        initiative_count >= 3

        and

        aligned_count >= 3

        and

        markup_momentum > 0

    ):

        inferred_intent = (
            "continuation_intent"
        )

        intent_strength = (

            initiative_count

            *

            markup_momentum

        )

    # =====================================
    # LIQUIDITY SWEEP
    # =====================================

    elif (

        absorption_count >= 1

        and

        expansion_momentum > 0

        and

        conflict_count >= 1

    ):

        inferred_intent = (
            "liquidity_sweep"
        )

        intent_strength = (

            absorption_count

            *

            expansion_momentum

        )

    # =====================================
    # BREAKOUT FAILURE
    # =====================================

    elif (

        initiative_count >= 2

        and

        no_demand_count >= 2

        and

        markdown_momentum > 0

    ):

        inferred_intent = (
            "breakout_failure"
        )

        intent_strength = (

            no_demand_count

            *

            markdown_momentum

        )

    # =====================================
    # INVENTORY TRANSFER
    # =====================================

    elif (

        absorption_count >= 1

        and

        initiative_count >= 2

        and

        no_supply_count >= 1

    ):

        inferred_intent = (
            "inventory_transfer"
        )

        intent_strength = (

            initiative_count

            *

            absorption_count

        )

    # =====================================
    # EXHAUSTION INTENT
    # =====================================

    elif (

        expansion_momentum < 0

        and

        no_demand_count >= 2

    ):

        inferred_intent = (
            "exhaustion_intent"
        )

        intent_strength = (

            abs(expansion_momentum)

            *

            no_demand_count

        )

    # =====================================
    # ABSORPTION CONTINUATION
    # =====================================

    elif (

        absorption_count >= 1

        and

        markup_momentum > 0

        and

        aligned_count >= 2

    ):

        inferred_intent = (
            "absorption_continuation"
        )

        intent_strength = (

            absorption_count

            *

            markup_momentum

        )

    # =====================================
    # SAVE
    # =====================================

    intent_row = {

        "timestamp": timestamp,

        "inferred_intent": inferred_intent,

        "intent_strength": intent_strength,

        "absorption_count": absorption_count,

        "initiative_count": initiative_count,

        "no_demand_count": no_demand_count,

        "no_supply_count": no_supply_count,

        "conflict_count": conflict_count,

        "aligned_count": aligned_count,

        "markup_momentum": markup_momentum,

        "markdown_momentum": markdown_momentum,

        "expansion_momentum": expansion_momentum

    }

    intent_states.append(
        intent_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

intent_df = pd.DataFrame(
    intent_states
)

# =====================================
# SAVE MEMORY
# =====================================

intent_df.to_parquet(
    "intent_inference_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("INTENT INFERENCE DEBUG")

print("=" * 50)

print()

print("INTENT DISTRIBUTION:")

print(

    intent_df["inferred_intent"]

    .value_counts()

)

print()

print("LAST 30 INTENT STATES:")

debug_cols = [

    "inferred_intent",

    "intent_strength",

    "absorption_count",

    "initiative_count",

    "no_demand_count",

    "no_supply_count",

    "conflict_count",

    "aligned_count",

    "markup_momentum",

    "markdown_momentum",

    "expansion_momentum"

]

print(

    intent_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "intent_inference_memory.parquet"
)

print()
