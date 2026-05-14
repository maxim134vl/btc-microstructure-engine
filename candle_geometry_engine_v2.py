import pandas as pd
import numpy as np

print("\nCANDLE GEOMETRY ENGINE V2 STARTED\n")

# =====================================
# LOAD MARKET FEED
# =====================================

df = pd.read_parquet(
    "live_market_feed.parquet"
)

df = df.sort_values(
    "timestamp"
).copy()

# =====================================
# BASIC STRUCTURE
# =====================================

df["spread"] = (
    df["high"] - df["low"]
)

df["body"] = abs(
    df["close"] - df["open"]
)

df["upper_wick"] = np.where(

    df["close"] >= df["open"],

    df["high"] - df["close"],

    df["high"] - df["open"]

)

df["lower_wick"] = np.where(

    df["close"] >= df["open"],

    df["open"] - df["low"],

    df["close"] - df["low"]

)

# =====================================
# CANDLE TYPE
# =====================================

df["candle_type"] = np.where(

    df["close"] > df["open"],

    "bullish",

    np.where(

        df["close"] < df["open"],

        "bearish",

        "neutral"

    )

)

# =====================================
# BODY POSITION
# =====================================

df["body_position"] = (
    (
        (
            df["open"] + df["close"]
        ) / 2
    )
    -
    df["low"]
) / (
    df["spread"] + 0.000001
)

# =====================================
# CLOSE ACCEPTANCE
# =====================================

df["close_position"] = (
    (
        df["close"] - df["low"]
    )
    /
    (
        df["spread"] + 0.000001
    )
)

# =====================================
# WICK DOMINANCE
# =====================================

df["upper_wick_ratio"] = (
    df["upper_wick"]
    /
    (
        df["spread"] + 0.000001
    )
)

df["lower_wick_ratio"] = (
    df["lower_wick"]
    /
    (
        df["spread"] + 0.000001
    )
)

# =====================================
# REJECTION LOGIC
# =====================================

df["upper_rejection"] = np.where(

    (
        df["upper_wick_ratio"] > 0.4
    )
    &
    (
        df["close_position"] < 0.6
    ),

    True,

    False

)

df["lower_rejection"] = np.where(

    (
        df["lower_wick_ratio"] > 0.4
    )
    &
    (
        df["close_position"] > 0.4
    ),

    True,

    False

)

# =====================================
# SPREAD QUALITY
# =====================================

spread_mean = (
    df["spread"]
    .rolling(20)
    .mean()
)

spread_std = (
    df["spread"]
    .rolling(20)
    .std()
)

df["spread_zscore"] = (
    (
        df["spread"]
        - spread_mean
    )
    /
    (
        spread_std + 0.000001
    )
)

# =====================================
# STRUCTURE LABEL
# =====================================

labels = []

for _, row in df.iterrows():

    label = "balanced"

    # absorption candidate

    if (

        row["lower_rejection"]

        and

        row["spread_zscore"] > 1

    ):

        label = "potential_absorption"

    # distribution candidate

    elif (

        row["upper_rejection"]

        and

        row["spread_zscore"] > 1

    ):

        label = "potential_distribution"

    # weak candle

    elif (

        row["body"]

        <
        (
            row["spread"] * 0.3
        )

    ):

        label = "indecision"

    labels.append(label)

df["structure_label"] = labels

# =====================================
# SAVE MEMORY
# =====================================

df.to_parquet(
    "candle_geometry_v2_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("GEOMETRY DEBUG")

print("=" * 50)

print()

print("STRUCTURE DISTRIBUTION:")

print(
    df["structure_label"]
    .value_counts()
)

print()

debug_cols = [

    "timestamp",

    "candle_type",

    "spread",

    "body",

    "upper_wick",

    "lower_wick",

    "upper_rejection",

    "lower_rejection",

    "spread_zscore",

    "structure_label"

]

print(
    df[debug_cols]
    .tail(20)
)

print()

print("MEMORY SAVED:")

print(
    "candle_geometry_v2_memory.parquet"
)

print()
