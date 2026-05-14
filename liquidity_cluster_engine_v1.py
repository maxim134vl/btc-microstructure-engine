import pandas as pd
import numpy as np

print("\nLIQUIDITY CLUSTER ENGINE STARTED\n")

# =====================================
# LOAD ZONES
# =====================================

zones = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

zones = zones.sort_values(
    "timestamp"
).copy()

# =====================================
# SETTINGS
# =====================================

merge_distance_pct = 0.003

# =====================================
# STORAGE
# =====================================

clusters = []

current_cluster = None

cluster_id = 0

# =====================================
# LOOP
# =====================================

for _, row in zones.iterrows():

    zone_low = row["zone_low"]

    zone_high = row["zone_high"]

    zone_mid = (
        zone_low + zone_high
    ) / 2

    behavior = row["behavior"]

    volume = row[
        "estimated_local_volume"
    ]

    # =====================================
    # FIRST CLUSTER
    # =====================================

    if current_cluster is None:

        current_cluster = {

            "cluster_id": cluster_id,

            "zone_low": zone_low,

            "zone_high": zone_high,

            "mid": zone_mid,

            "touches": 1,

            "total_volume": volume,

            "behaviors": [behavior]

        }

        continue

    # =====================================
    # DISTANCE
    # =====================================

    cluster_mid = current_cluster["mid"]

    distance_pct = abs(

        zone_mid - cluster_mid

    ) / cluster_mid

    # =====================================
    # MERGE
    # =====================================

    if distance_pct < merge_distance_pct:

        current_cluster["zone_low"] = min(

            current_cluster["zone_low"],
            zone_low

        )

        current_cluster["zone_high"] = max(

            current_cluster["zone_high"],
            zone_high

        )

        current_cluster["mid"] = (

            current_cluster["zone_low"]
            +
            current_cluster["zone_high"]

        ) / 2

        current_cluster["touches"] += 1

        current_cluster["total_volume"] += volume

        current_cluster["behaviors"].append(
            behavior
        )

    # =====================================
    # NEW CLUSTER
    # =====================================

    else:

        clusters.append(
            current_cluster
        )

        cluster_id += 1

        current_cluster = {

            "cluster_id": cluster_id,

            "zone_low": zone_low,

            "zone_high": zone_high,

            "mid": zone_mid,

            "touches": 1,

            "total_volume": volume,

            "behaviors": [behavior]

        }

# =====================================
# FINAL SAVE
# =====================================

if current_cluster is not None:

    clusters.append(
        current_cluster
    )

# =====================================
# BUILD DF
# =====================================

cluster_df = pd.DataFrame(
    clusters
)

# =====================================
# DOMINANT BEHAVIOR
# =====================================

cluster_df["dominant_behavior"] = (

    cluster_df["behaviors"]

    .apply(

        lambda x:

        max(
            set(x),
            key=x.count
        )

    )

)

# =====================================
# SAVE
# =====================================

cluster_df.to_parquet(
    "liquidity_clusters_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("CLUSTER DEBUG")

print("=" * 50)

print()

print(
    cluster_df[
        [

            "cluster_id",

            "zone_low",

            "zone_high",

            "touches",

            "total_volume",

            "dominant_behavior"

        ]

    ]
    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "liquidity_clusters_memory.parquet"
)

print()
