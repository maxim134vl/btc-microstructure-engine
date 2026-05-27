import pandas as pd
import numpy as np

print("\nFLOW LIQUIDITY INTERACTION ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

flow = pd.read_parquet(
    "live_volume_flow_memory.parquet"
)

clusters = pd.read_parquet(
    "liquidity_clusters_memory.parquet"
)
# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    "live_market_feed.parquet"
)

feed = feed.sort_values(
    "timestamp"
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
    # CURRENT MARKET LEVEL
    # =====================================

    current_level = (

    feed_map.loc[
        timestamp
    ]["close"]

    )
    # approximate current level

    current_level = abs(price)

    interaction_type = "neutral"

    matched_cluster = None

    # =====================================
    # FIND CLUSTER
    # =====================================

    for _, cluster in clusters.iterrows():

        cluster_low = cluster["zone_low"]

        cluster_high = cluster["zone_high"]

        cluster_mid = (

            cluster_low
            +
            cluster_high

        ) / 2

        distance_pct = abs(

            current_level
            -
            cluster_mid

        ) / cluster_mid

        # nearby structure

        if distance_pct < 0.003:

            matched_cluster = (
                cluster["cluster_id"]
            )

            dominant_behavior = (

                cluster[
                    "dominant_behavior"
                ]

            )

            # =====================================
            # COMPRESSION
            # =====================================

            if (

                flow_state
                ==
                "compression"

            ):

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
            # FAILED EXPANSION
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
    # SAVE
    # =====================================

    interaction_rows.append({

        "timestamp":
            timestamp,

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
    "flow_liquidity_interaction_memory.parquet",
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
