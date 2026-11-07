import pandas as pd
import numpy as np

from storage.path_registry import resolve_read, resolve_write

print("\nVOLUME CLASSIFICATION ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    resolve_read("candle_structure_memory.parquet")
)

df = df.dropna().copy()

# =====================================
# DEFAULT CLASS
# =====================================

df["volume_class"] = "high_average"

# =====================================
# LOW / SMALL VOLUME
# =====================================

low_volume_condition = (

    df["volume_zscore"] < -0.7

)

df.loc[
    low_volume_condition,
    "volume_class"
] = "low_small"

# =====================================
# CLIMAX CONDITIONS
# =====================================

buying_climax = (

    (df["candle_type"] == "bullish")

    &

    (df["spread_zscore"] > 1.5)

    &

    (df["volume_zscore"] > 1.5)

)

selling_climax = (

    (df["candle_type"] == "bearish")

    &

    (df["spread_zscore"] > 1.5)

    &

    (df["volume_zscore"] > 1.5)

)

df.loc[
    buying_climax,
    "volume_class"
] = "climax"

df.loc[
    selling_climax,
    "volume_class"
] = "climax"

# =====================================
# STOPPING VOLUME
# =====================================

stopping_volume = (

    (df["candle_type"] == "bearish")

    &

    (df["volume_zscore"] > 0.7)

    &

    (df["lower_wick"] > df["body"])

    &

    (df["close_position"] > 0.5)

)

df.loc[
    stopping_volume,
    "volume_class"
] = "stopping"

# =====================================
# SAVE MEMORY
# =====================================

df.to_parquet(
    resolve_write("volume_classification_memory.parquet")
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("VOLUME CLASSIFICATION DEBUG")

print("=" * 50)

print()

print("CLASS DISTRIBUTION:")

print(
    df["volume_class"]
    .value_counts()
)

print()

print("LAST 20 CLASSIFIED CANDLES:")

debug_cols = [

    "open",
    "high",
    "low",
    "close",

    "candle_type",

    "spread",
    "body",

    "upper_wick",
    "lower_wick",

    "volume",

    "spread_zscore",

    "volume_zscore",

    "close_position",

    "volume_class"

]

print(

    df[debug_cols]

    .tail(20)

)

print()

print("MEMORY SAVED:")

print(
    "volume_classification_memory.parquet"
)

print()
