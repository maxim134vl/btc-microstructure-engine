import pandas as pd
import numpy as np

print("\nHTF LTF CONTEXT ENGINE STARTED\n")

# =====================================
# LOAD FLOW
# =====================================

flow = pd.read_parquet(
    "live_volume_flow_memory.parquet"
)

# =====================================
# LOAD INTERACTIONS
# =====================================

interactions = pd.read_parquet(
    "flow_liquidity_interaction_memory.parquet"
)

# =====================================
# LOAD HTF
# =====================================

htf = pd.read_parquet(
    "htf_structure_memory.parquet"
)

# =====================================
# CLEAN
# =====================================

flow = flow.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

interactions = interactions.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

htf = htf.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

# =====================================
# MAPS
# =====================================

flow_map = flow.set_index(
    "timestamp"
)

interaction_map = interactions.set_index(
    "timestamp"
)

htf_map = htf.set_index(
    "timestamp"
)

# =====================================
# COMMON TIMESTAMPS
# =====================================

timestamps = sorted(

    list(

        set(flow_map.index)

        &

        set(interaction_map.index)

        &

        set(htf_map.index)

    )

)

# =====================================
# STORAGE
# =====================================

context_rows = []

# =====================================
# LOOP
# =====================================

for timestamp in timestamps:

    flow_state = str(

        flow_map.loc[
            timestamp
        ]["flow_state"]

    )

    interaction_type = str(

        interaction_map.loc[
            timestamp
        ]["interaction_type"]

    )

    htf_structure = str(

        htf_map.loc[
            timestamp
        ]["htf_structure"]

    )

    htf_direction = str(

        htf_map.loc[
            timestamp
        ]["htf_direction"]

    )

    # =====================================
    # CONTEXT
    # =====================================

    contextual_alignment = (
        "neutral_alignment"
    )

    # =====================================
    # COMPRESSION BREAKOUT
    # =====================================

    if (

        flow_state
        ==
        "compression"

        and

        htf_structure
        ==
        "compression_structure"

    ):

        contextual_alignment = (
            "nested_compression"
        )

    # =====================================
    # EXPANSION INSIDE HTF EXPANSION
    # =====================================

    elif (

        flow_state
        ==
        "aggressive_expansion"

        and

        htf_structure
        ==
        "directional_expansion"

    ):

        contextual_alignment = (
            "aligned_expansion"
        )

    # =====================================
    # EXHAUSTION AGAINST HTF
    # =====================================

    elif (

        interaction_type
        ==
        "exhaustion_at_liquidity"

        and

        htf_structure
        ==
        "directional_expansion"

    ):

        contextual_alignment = (
            "countertrend_exhaustion"
        )

    # =====================================
    # FAILED BREAKOUT INSIDE COMPRESSION
    # =====================================

    elif (

        interaction_type
        ==
        "failed_breakout_behavior"

        and

        htf_structure
        ==
        "compression_structure"

    ):

        contextual_alignment = (
            "failed_compression_breakout"
        )

    # =====================================
    # DISTRIBUTION INSIDE BULLISH HTF
    # =====================================

    elif (

        interaction_type
        ==
        "expansion_into_distribution"

        and

        htf_direction
        ==
        "bullish"

    ):

        contextual_alignment = (
            "bullish_distribution_warning"
        )

    # =====================================
    # SAVE
    # =====================================

    context_rows.append({

        "timestamp":
            timestamp,

        "flow_state":
            flow_state,

        "interaction_type":
            interaction_type,

        "htf_structure":
            htf_structure,

        "htf_direction":
            htf_direction,

        "contextual_alignment":
            contextual_alignment

    })

# =====================================
# BUILD DF
# =====================================

context_df = pd.DataFrame(
    context_rows
)

# =====================================
# SAVE
# =====================================

context_df.to_parquet(

    "htf_ltf_context_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("CONTEXT DISTRIBUTION")

print("=" * 50)

print()

print(

    context_df[
        "contextual_alignment"
    ].value_counts()

)

print()

print(
    context_df.tail(40)
)

print()

print("MEMORY SAVED:")

print(
    "htf_ltf_context_memory.parquet"
)

print()
