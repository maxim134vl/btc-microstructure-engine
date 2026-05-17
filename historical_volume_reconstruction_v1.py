import pandas as pd
import numpy as np

print()
print(
    "HISTORICAL VOLUME RECONSTRUCTION"
)
print()

# =====================================
# LOAD DATA
# =====================================

df = pd.read_parquet(
    "candle_structure_memory.parquet"
)

df = df.reset_index()

print()
print(
    "TOTAL CANDLES:",
    len(df)
)

# =====================================
# RELATIVE METRICS
# =====================================

df["relative_volume"] = (

    df["volume"]

    /

    df["volume"]
    .rolling(20)
    .mean()

)

df["relative_spread"] = (

    df["spread"]

    /

    df["spread"]
    .rolling(20)
    .mean()

)

# =====================================
# PRICE CHANGE
# =====================================

df["price_change"] = (

    df["close"]

    -

    df["open"]

)

# =====================================
# DELTA EFFICIENCY
# =====================================

df["delta_efficiency"] = (

    df["price_change"]

    /

    (
        df["delta"]
        .abs()
        + 1
    )

)

# =====================================
# VOLUME CLASSIFICATION
# =====================================

conditions = [

    (
        (df["relative_volume"] > 2.0)

        &

        (df["close_position"] < 0.3)
    ),

    (
        (df["relative_volume"] > 1.5)

        &

        (df["spread_zscore"] > 1.0)
    ),

    (
        (df["relative_volume"] < 0.7)
    )

]

choices = [

    "stopping",

    "climax",

    "low_small"

]

df["volume_class"] = np.select(

    conditions,
    choices,
    default="high_average"

)

# =====================================
# PARTICIPATION
# =====================================

df["participation_state"] = np.where(

    df["relative_volume"] > 1.5,

    "HIGH_PARTICIPATION",

    "NORMAL_PARTICIPATION"

)

# =====================================
# EFFORT VS RESULT
# =====================================

df["effort_result_ratio"] = (

    abs(df["delta"])

    /

    (
        abs(df["spread"])
        + 1e-9
    )

)

df["effort_result_state"] = np.where(

    df["effort_result_ratio"] > 25,

    "INEFFICIENT_EFFORT",

    "BALANCED_RESPONSE"

)

# =====================================
# UNFINISHED AUCTION
# =====================================

df["unfinished_auction"] = np.where(

    (
        (df["upper_wick"] > df["body"])

        |

        (df["lower_wick"] > df["body"])
    ),

    True,

    False

)

# =====================================
# CONTINUATION QUALITY
# =====================================

df["continuation_quality"] = np.where(

    (
        (df["close_position"] > 0.7)

        &

        (df["spread_zscore"] > 0)
    ),

    "STRONG",

    "WEAK"

)

# =====================================
# SAVE
# =====================================

cols = [

    "timestamp",

    "volume_class",

    "participation_state",

    "effort_result_state",

    "unfinished_auction",

    "continuation_quality",

    "delta_efficiency",

    "relative_volume",

    "relative_spread"

]

historical = df[cols].copy()

historical.to_parquet(
    "historical_volume_cognition.parquet"
)

print()
print(
    "HISTORICAL VOLUME COGNITION SAVED"
)

print()
print(
    historical.tail(10)
)

print()
