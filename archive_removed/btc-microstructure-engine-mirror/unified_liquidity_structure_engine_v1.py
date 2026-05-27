import pandas as pd
import numpy as np

print("\nUNIFIED LIQUIDITY STRUCTURE ENGINE STARTED\n")

# =====================================
# LOAD MEMORIES
# =====================================

df = pd.read_parquet(
    "behavioral_scoring_memory.parquet"
)

micro_zones = pd.read_parquet(
    "volume_location_memory.parquet"
)

df = df.dropna().copy()

# =====================================
# STORAGE
# =====================================

liquidity_map = []

# =====================================
# MAIN LOOP
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = df.index[i]

    volume_class = row["volume_class"]

    # =====================================
    # DEFAULT STRUCTURE
    # =====================================

    structure = {

        "timestamp": timestamp,

        "volume_class": volume_class,

        "close": row["close"],

        "spread_score": row["spread_score"],

        "volume_score": row["volume_score"],

        "trend_pressure_score": row["trend_pressure_score"],

        "participation_score": row["participation_score"],

        "directional_score": row["directional_score"],

        "lower_rejection_score": row["lower_rejection_score"],

        "upper_rejection_score": row["upper_rejection_score"],

        "imbalance_score": row["imbalance_score"],

        "behavior": "undefined",

        "liquidity_type": "undefined",

        "micro_zone_low": np.nan,

        "micro_zone_high": np.nan

    }

    # =====================================
    # LOW / SMALL VOLUME
    # =====================================

    if volume_class == "low_small":

        if row["candle_type"] == "bullish":

            structure["behavior"] = "no_demand"

            structure["liquidity_type"] = "passive_buying"

        else:

            structure["behavior"] = "no_supply"

            structure["liquidity_type"] = "passive_selling"

    # =====================================
    # HIGH / AVERAGE
    # =====================================

    elif volume_class == "high_average":

        if row["directional_score"] > 0.6:

            structure["behavior"] = "initiative_participation"

            structure["liquidity_type"] = "trend_participation"

        else:

            structure["behavior"] = "balanced_participation"

            structure["liquidity_type"] = "balanced_auction"

    # =====================================
    # STOPPING
    # =====================================

    elif volume_class == "stopping":

        structure["behavior"] = "absorption"

        structure["liquidity_type"] = "defended_liquidity"

        matching_zone = micro_zones.loc[

            micro_zones["timestamp"]

            ==

            timestamp

        ]

        if len(matching_zone) > 0:

            structure["micro_zone_low"] = (

                matching_zone.iloc[0][
                    "micro_zone_low"
                ]

            )

            structure["micro_zone_high"] = (

                matching_zone.iloc[0][
                    "micro_zone_high"
                ]

            )

    # =====================================
    # CLIMAX
    # =====================================

    elif volume_class == "climax":

        structure["behavior"] = "exhaustion"

        structure["liquidity_type"] = "terminal_auction"

        matching_zone = micro_zones.loc[

            micro_zones["timestamp"]

            ==

            timestamp

        ]

        if len(matching_zone) > 0:

            structure["micro_zone_low"] = (

                matching_zone.iloc[0][
                    "micro_zone_low"
                ]

            )

            structure["micro_zone_high"] = (

                matching_zone.iloc[0][
                    "micro_zone_high"
                ]

            )

    # =====================================
    # SAVE STRUCTURE
    # =====================================

    liquidity_map.append(
        structure
    )

# =====================================
# BUILD DATAFRAME
# =====================================

liquidity_df = pd.DataFrame(
    liquidity_map
)

# =====================================
# SAVE MEMORY
# =====================================

liquidity_df.to_parquet(
    "unified_liquidity_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("LIQUIDITY STRUCTURE DEBUG")

print("=" * 50)

print()

print("BEHAVIOR DISTRIBUTION:")

print(

    liquidity_df["behavior"]

    .value_counts()

)

print()

print("LIQUIDITY TYPES:")

print(

    liquidity_df["liquidity_type"]

    .value_counts()

)

print()

print("LAST 20 STRUCTURES:")

debug_cols = [

    "volume_class",

    "behavior",

    "liquidity_type",

    "spread_score",

    "volume_score",

    "trend_pressure_score",

    "participation_score",

    "directional_score",

    "micro_zone_low",

    "micro_zone_high"

]

print(

    liquidity_df[debug_cols]

    .tail(20)

)

print()

print("MEMORY SAVED:")

print(
    "unified_liquidity_memory.parquet"
)

print()
