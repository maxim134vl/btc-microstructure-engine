import pandas as pd
import numpy as np

print("\nINCREMENTAL VOLUME LOCALIZATION V3 STARTED\n")

# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    "live_market_feed.parquet"
)

feed = feed.sort_values(
    "timestamp"
)

latest = feed.iloc[-1]

# =====================================
# LOAD GEOMETRY
# =====================================

geometry = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

latest_geometry = geometry.iloc[-1]

# =====================================
# LOAD MEMORY
# =====================================

memory_file = (
    "volume_localization_v2_memory.parquet"
)

try:

    memory = pd.read_parquet(
        memory_file
    )

except:

    memory = pd.DataFrame()

# =====================================
# DUPLICATE CHECK
# =====================================

if len(memory) > 0:

    latest_memory_ts = (

        memory.iloc[-1]["timestamp"]

    )

    if latest["timestamp"] == latest_memory_ts:

        print(
            "NO NEW LOCALIZATION\n"
        )

        exit()

# =====================================
# EXTRACT
# =====================================

high_price = latest["high"]

low_price = latest["low"]

open_price = latest["open"]

close_price = latest["close"]

volume = latest["volume"]

spread = (
    high_price - low_price
)

body = abs(
    close_price - open_price
)

upper_wick = (

    high_price
    -
    max(
        open_price,
        close_price
    )

)

lower_wick = (

    min(
        open_price,
        close_price
    )
    -
    low_price

)

structure = latest_geometry[
    "structure_label"
]

# =====================================
# DEFAULT
# =====================================

behavior = (
    "body_participation"
)

zone_low = min(
    open_price,
    close_price
)

zone_high = max(
    open_price,
    close_price
)

concentration = 0.5

# =====================================
# ABSORPTION
# =====================================

if structure == "potential_absorption":

    behavior = (
        "localized_absorption"
    )

    zone_low = low_price + (
        lower_wick * 0.15
    )

    zone_high = low_price + (
        lower_wick * 0.55
    )

    concentration = 0.7

# =====================================
# DISTRIBUTION
# =====================================

elif structure == (
    "potential_distribution"
):

    behavior = (
        "localized_distribution"
    )

    wick_start = max(
        open_price,
        close_price
    )

    zone_low = wick_start + (
        upper_wick * 0.15
    )

    zone_high = wick_start + (
        upper_wick * 0.55
    )

    concentration = 0.7

# =====================================
# ESTIMATED LOCAL VOLUME
# =====================================

localized_volume = (
    volume * concentration
)

# =====================================
# BUILD ROW
# =====================================

new_row = pd.DataFrame([{

    "timestamp":
        latest["timestamp"],

    "behavior":
        behavior,

    "zone_low":
        round(zone_low, 4),

    "zone_high":
        round(zone_high, 4),

    "zone_width":
        round(
            zone_high - zone_low,
            4
        ),

    "estimated_local_volume":
        localized_volume,

    "total_volume":
        volume,

    "volume_concentration":
        concentration

}])

# =====================================
# APPEND
# =====================================

memory = pd.concat(

    [
        memory,
        new_row
    ],

    ignore_index=True

)

# =====================================
# SAVE
# =====================================

memory.to_parquet(
    memory_file,
    index=False
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("NEW LOCALIZATION STATE")

print("=" * 50)

print()

print(new_row)

print()

print("MEMORY UPDATED")

print()
