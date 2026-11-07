import pandas as pd
import numpy as np

print("\nVOLUME LOCALIZATION ENGINE V2 STARTED\n")

# =====================================
# LOAD GEOMETRY
# =====================================

df = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

df = df.copy()

# =====================================
# STORAGE
# =====================================

micro_zones = []

# =====================================
# LOOP
# =====================================

for _, row in df.iterrows():

    spread = row["spread"]

    high = row["high"]

    low = row["low"]

    open_price = row["open"]

    close_price = row["close"]

    volume = row["volume"]

    upper_wick = row["upper_wick"]

    lower_wick = row["lower_wick"]

    candle_type = row["candle_type"]

    structure_label = row["structure_label"]

    # =====================================
    # DEFAULT
    # =====================================

    localized_zone_low = low
    localized_zone_high = high

    localized_volume_ratio = 0.3

    localized_behavior = "neutral"

    # =====================================
    # LOWER ABSORPTION
    # =====================================

    if (

        row["lower_rejection"]

        and

        lower_wick > (
            spread * 0.35
        )

    ):

        wick_base = low

        wick_top = low + lower_wick

        localized_zone_low = (
            wick_base
            + (lower_wick * 0.25)
        )

        localized_zone_high = (
            wick_base
            + (lower_wick * 0.45)
        )

        localized_volume_ratio = 0.7

        localized_behavior = (
            "localized_absorption"
        )

    # =====================================
    # UPPER DISTRIBUTION
    # =====================================

    elif (

        row["upper_rejection"]

        and

        upper_wick > (
            spread * 0.35
        )

    ):

        wick_top = high

        wick_bottom = high - upper_wick

        localized_zone_low = (
            wick_bottom
            + (upper_wick * 0.55)
        )

        localized_zone_high = (
            wick_bottom
            + (upper_wick * 0.80)
        )

        localized_volume_ratio = 0.7

        localized_behavior = (
            "localized_distribution"
        )

    # =====================================
    # BODY PARTICIPATION
    # =====================================

    else:

        body_low = min(
            open_price,
            close_price
        )

        body_high = max(
            open_price,
            close_price
        )

        localized_zone_low = (
            body_low
        )

        localized_zone_high = (
            body_high
        )

        localized_volume_ratio = 0.5

        localized_behavior = (
            "body_participation"
        )

    # =====================================
    # ESTIMATED LOCAL VOLUME
    # =====================================

    estimated_local_volume = (
        volume
        *
        localized_volume_ratio
    )

    # =====================================
    # SAVE
    # =====================================

    micro_zone = {

        "timestamp": row["timestamp"],

        "behavior": localized_behavior,

        "zone_low": localized_zone_low,

        "zone_high": localized_zone_high,

        "zone_width": (
            localized_zone_high
            -
            localized_zone_low
        ),

        "estimated_local_volume":
            estimated_local_volume,

        "total_volume": volume,

        "volume_concentration": (
            estimated_local_volume
            /
            (
                volume + 0.000001
            )
        )

    }

    micro_zones.append(
        micro_zone
    )

# =====================================
# BUILD DF
# =====================================

zones_df = pd.DataFrame(
    micro_zones
)

# =====================================
# SAVE
# =====================================

zones_df.to_parquet(
    "volume_localization_v2_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("LOCALIZATION DEBUG")

print("=" * 50)

print()

print("BEHAVIOR DISTRIBUTION:")

print(
    zones_df["behavior"]
    .value_counts()
)

print()

print(
    zones_df.tail(20)
)

print()

print("MEMORY SAVED:")

print(
    "volume_localization_v2_memory.parquet"
)

print()
