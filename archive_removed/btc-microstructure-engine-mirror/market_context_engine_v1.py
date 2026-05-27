import pandas as pd
import numpy as np

print("\nMARKET CONTEXT ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "volume_classification_memory.parquet"
)

df = df.dropna().copy()

# =====================================
# PRICE CHANGE
# =====================================

df["price_change"] = (

    df["close"]

    -

    df["open"]

)

# =====================================
# ROLLING PRICE MOVEMENT
# =====================================

df["rolling_price_move_5"] = (

    df["price_change"]

    .rolling(5)

    .sum()

)

df["rolling_price_move_10"] = (

    df["price_change"]

    .rolling(10)

    .sum()

)

# =====================================
# ROLLING SPREAD
# =====================================

df["rolling_spread_5"] = (

    df["spread"]

    .rolling(5)

    .mean()

)

df["rolling_spread_10"] = (

    df["spread"]

    .rolling(10)

    .mean()

)

# =====================================
# SPREAD EXPANSION
# =====================================

df["spread_expansion"] = (

    df["spread"]

    /

    (

        df["rolling_spread_10"]

        +

        0.000001

    )

)

# =====================================
# VOLUME EXPANSION
# =====================================

df["volume_expansion"] = (

    df["volume"]

    /

    (

        df["volume_mean_20"]

        +

        0.000001

    )

)

# =====================================
# DIRECTIONAL CONTEXT
# =====================================

conditions = [

    df["rolling_price_move_5"] > 0,

    df["rolling_price_move_5"] < 0

]

choices = [

    "bullish",

    "bearish"

]

df["prior_trend"] = np.select(

    conditions,

    choices,

    default="neutral"

)

# =====================================
# AGGRESSIVE MOVEMENT
# =====================================

df["aggressive_move"] = np.where(

    (

        df["spread_expansion"] > 1.5

    )

    &

    (

        abs(

            df["rolling_price_move_5"]

        )

        >

        df["spread"]

    ),

    True,

    False

)

# =====================================
# EXHAUSTION RISK
# =====================================

df["exhaustion_risk"] = np.where(

    (

        df["volume_expansion"] > 1.5

    )

    &

    (

        df["close_position"]

        < 0.4

    )

    &

    (

        df["candle_type"]

        == "bullish"

    ),

    True,

    False

)

# =====================================
# AUCTION STATE
# =====================================

auction_conditions = [

    (

        (df["prior_trend"] == "bullish")

        &

        (df["aggressive_move"] == True)

    ),

    (

        (df["prior_trend"] == "bearish")

        &

        (df["aggressive_move"] == True)

    )

]

auction_choices = [

    "aggressive_buying",

    "aggressive_selling"

]

df["auction_state"] = np.select(

    auction_conditions,

    auction_choices,

    default="balanced"

)

# =====================================
# SAVE MEMORY
# =====================================

df.to_parquet(
    "market_context_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("MARKET CONTEXT DEBUG")

print("=" * 50)

print()

print("AUCTION STATE DISTRIBUTION:")

print(

    df["auction_state"]

    .value_counts()

)

print()

print("LAST 20 CONTEXT ROWS:")

debug_cols = [

    "close",

    "price_change",

    "rolling_price_move_5",

    "spread",

    "spread_expansion",

    "volume",

    "volume_expansion",

    "prior_trend",

    "aggressive_move",

    "exhaustion_risk",

    "auction_state",

    "volume_class"

]

print(

    df[debug_cols]

    .tail(20)

)

print()

print("MEMORY SAVED:")

print(
    "market_context_memory.parquet"
)

print()
