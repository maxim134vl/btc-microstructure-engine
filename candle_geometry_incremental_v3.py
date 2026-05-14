import pandas as pd
import numpy as np

print("\nINCREMENTAL GEOMETRY ENGINE V3 STARTED\n")

# =====================================
# LOAD LIVE FEED
# =====================================

feed = pd.read_parquet(
    "live_market_feed.parquet"
)

feed = feed.sort_values(
    "timestamp"
)

latest = feed.iloc[-1]

# =====================================
# LOAD MEMORY
# =====================================

memory_file = (
    "candle_geometry_v2_memory.parquet"
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
            "NO NEW CANDLE\n"
        )

        exit()

# =====================================
# EXTRACT OHLC
# =====================================

open_price = latest["open"]

high_price = latest["high"]

low_price = latest["low"]

close_price = latest["close"]

# =====================================
# GEOMETRY
# =====================================

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

# =====================================
# CANDLE TYPE
# =====================================

candle_type = (
    "bullish"
    if close_price >= open_price
    else "bearish"
)

# =====================================
# REJECTION
# =====================================

upper_rejection = (

    upper_wick
    >
    body

)

lower_rejection = (

    lower_wick
    >
    body

)

# =====================================
# STRUCTURE LABEL
# =====================================

structure_label = "balanced"

if lower_rejection:

    structure_label = (
        "potential_absorption"
    )

elif upper_rejection:

    structure_label = (
        "potential_distribution"
    )

elif body < (spread * 0.25):

    structure_label = (
        "indecision"
    )

# =====================================
# BUILD ROW
# =====================================

new_row = pd.DataFrame([{

    "timestamp":
        latest["timestamp"],

    "candle_type":
        candle_type,

    "spread":
        spread,

    "body":
        body,

    "upper_wick":
        upper_wick,

    "lower_wick":
        lower_wick,

    "upper_rejection":
        upper_rejection,

    "lower_rejection":
        lower_rejection,

    "structure_label":
        structure_label

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

print("NEW GEOMETRY STATE")

print("=" * 50)

print()

print(new_row)

print()

print("MEMORY UPDATED")

print()
