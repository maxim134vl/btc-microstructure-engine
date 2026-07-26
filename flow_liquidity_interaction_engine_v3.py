import pandas as pd
import numpy as np

from storage.path_registry import resolve_read, resolve_write

print("\nFLOW LIQUIDITY INTERACTION ENGINE V3 STARTED\n")

# =====================================
# LOAD FLOW
# =====================================

flow = pd.read_parquet(
    resolve_read("live_volume_flow_memory.parquet")
)

# =====================================
# LOAD CLUSTERS
# =====================================

clusters = pd.read_parquet(
    resolve_read("liquidity_clusters_memory.parquet")
)

# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    resolve_read("live_market_feed.parquet")
)

feed = feed.sort_values(
    "timestamp"
)

# =====================================
# REMOVE DUPLICATES
# =====================================

feed = feed.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

feed_map = feed.set_index(
    "timestamp"
)

# =====================================
# STORAGE
# =====================================

interaction_rows = []

# =====================================
# LOOP FLOW
# =====================================

for _, row in flow.iterrows():

    timestamp = row["timestamp"]

    flow_state = row["flow_state"]

    # =====================================
    # GET MARKET LEVEL
    # =====================================

    if timestamp not in feed_map.index:

        continue

    current_level = float(

        feed_map.loc[
            timestamp
        ]["close"]

    )

    interaction_type = "neutral"

    matched_cluster = None

    # =====================================
    # LOOP CLUSTERS
    # =====================================

    for _, cluster in clusters.iterrows():

        cluster_low = float(
            cluster["zone_low"]
        )

        cluster_high = float(
            cluster["zone_high"]
        )

        dominant_behavior = str(

            cluster[
                "dominant_behavior"
            ]

        )

        # =====================================
        # INSIDE CLUSTER
        # =====================================

        inside_cluster = (

            current_level >= cluster_low

            and

            current_level <= cluster_high

        )

        if inside_cluster:

            matched_cluster = int(
                cluster["cluster_id"]
            )

            # =====================================
            # COMPRESSION
            # =====================================

            if flow_state == "compression":

                interaction_type = (
                    "compression_inside_liquidity"
                )

            # =====================================
            # EXPANSION INTO ABSORPTION
            # =====================================

            elif (

                flow_state
                ==
                "aggressive_expansion"

                and

                dominant_behavior
                ==
                "localized_absorption"

            ):

                interaction_type = (
                    "expansion_into_absorption"
                )

            # =====================================
            # EXPANSION INTO DISTRIBUTION
            # =====================================

            elif (

                flow_state
                ==
                "aggressive_expansion"

                and

                dominant_behavior
                ==
                "localized_distribution"

            ):

                interaction_type = (
                    "expansion_into_distribution"
                )

            # =====================================
            # FAILED BREAKOUT
            # =====================================

            elif (

                flow_state
                ==
                "failed_expansion"

            ):

                interaction_type = (
                    "failed_breakout_behavior"
                )

            # =====================================
            # EXHAUSTION
            # =====================================

            elif (

                flow_state
                ==
                "exhaustion"

            ):

                interaction_type = (
                    "exhaustion_at_liquidity"
                )

            break

    # =====================================
    # SAVE ROW
    # =====================================

    interaction_rows.append({

        "timestamp":
            timestamp,

        "market_level":
            current_level,

        "flow_state":
            flow_state,

        "matched_cluster":
            matched_cluster,

        "interaction_type":
            interaction_type

    })

# =====================================
# BUILD DF
# =====================================

interaction_df = pd.DataFrame(
    interaction_rows
)

# =====================================
# SAVE
# =====================================

interaction_df.to_parquet(

    resolve_write("flow_liquidity_interaction_memory.parquet"),

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("INTERACTION DISTRIBUTION")

print("=" * 50)

print()

print(

    interaction_df[
        "interaction_type"
    ].value_counts()

)

print()

print(

    interaction_df.tail(40)

)

print()

print("MEMORY SAVED:")

print(
    "flow_liquidity_interaction_memory.parquet"
)

print()
