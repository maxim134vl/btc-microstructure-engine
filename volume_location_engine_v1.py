import pandas as pd
import numpy as np

print("\nVOLUME LOCATION ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "behavioral_scoring_memory.parquet"
)

df = df.dropna().copy()

# =====================================
# STORAGE
# =====================================

zones = []

# =====================================
# LOOP
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = df.index[i]

    # =====================================
    # STOPPING DETECTION
    # =====================================

    stopping_condition = (

        row["volume_class"] == "stopping"

        and

        row["lower_rejection_score"] > 0.4

        and

        row["spread_score"] > 1

    )

    if stopping_condition:

        # =====================================
        # LOWER WICK RANGE
        # =====================================

        wick_low = row["low"]

        wick_high = min(
            row["open"],
            row["close"]
        )

        lower_wick_size = (

            wick_high

            -

            wick_low

        )

        # =====================================
        # MICRO LIQUIDITY AREA
        # =====================================

        micro_zone_low = (

            wick_low

            +

            lower_wick_size * 0.15

        )

        micro_zone_high = (

            wick_low

            +

            lower_wick_size * 0.35

        )

        # =====================================
        # CONFIDENCE
        # =====================================

        confidence = (

            row["lower_rejection_score"]

            *

            row["volume_score"]

            *

            row["spread_score"]

        )

        zone = {

            "timestamp": timestamp,

            "zone_type": "stopping",

            "candle_low": row["low"],

            "candle_high": row["high"],

            "micro_zone_low": micro_zone_low,

            "micro_zone_high": micro_zone_high,

            "lower_wick_size": lower_wick_size,

            "volume_score": row["volume_score"],

            "spread_score": row["spread_score"],

            "rejection_score": row["lower_rejection_score"],

            "confidence": confidence

        }

        zones.append(zone)

    # =====================================
    # BUYING CLIMAX
    # =====================================

    buying_climax = (

        row["volume_class"] == "climax"

        and

        row["candle_type"] == "bullish"

        and

        row["upper_rejection_score"] > 0.3

    )

    if buying_climax:

        wick_high = row["high"]

        wick_low = max(
            row["open"],
            row["close"]
        )

        upper_wick_size = (

            wick_high

            -

            wick_low

        )

        micro_zone_low = (

            wick_high

            -

            upper_wick_size * 0.35

        )

        micro_zone_high = (

            wick_high

            -

            upper_wick_size * 0.15

        )

        confidence = (

            row["upper_rejection_score"]

            *

            row["volume_score"]

            *

            row["spread_score"]

        )

        zone = {

            "timestamp": timestamp,

            "zone_type": "buying_climax",

            "candle_low": row["low"],

            "candle_high": row["high"],

            "micro_zone_low": micro_zone_low,

            "micro_zone_high": micro_zone_high,

            "upper_wick_size": upper_wick_size,

            "volume_score": row["volume_score"],

            "spread_score": row["spread_score"],

            "rejection_score": row["upper_rejection_score"],

            "confidence": confidence

        }

        zones.append(zone)

# =====================================
# SAVE
# =====================================

zones_df = pd.DataFrame(zones)

zones_df.to_parquet(
    "volume_location_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("MICRO ZONES FOUND")

print("=" * 50)

print()

if len(zones_df) > 0:

    print(

        zones_df[[
            "timestamp",

            "zone_type",

            "micro_zone_low",

            "micro_zone_high",

            "confidence",

            "volume_score",

            "spread_score",

            "rejection_score"

        ]]

    )

else:

    print("NO MICRO ZONES FOUND")

print()

print("MEMORY SAVED:")

print(
    "volume_location_memory.parquet"
)

print()
