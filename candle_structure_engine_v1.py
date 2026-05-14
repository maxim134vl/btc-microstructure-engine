import pandas as pd
import numpy as np

print("\nCANDLE STRUCTURE ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

flow = pd.read_parquet(
    "multi_exchange_flow.parquet"
)

flow["timestamp"] = pd.to_datetime(
    flow["timestamp"]
)

flow = flow.sort_values(
    "timestamp"
)

# =====================================
# BUILD OHLC
# =====================================

ohlc = flow.resample(
    "15min",
    on="timestamp"
).agg({

    "avg_price": [
        "first",
        "max",
        "min",
        "last"
    ],

    "buy_volume": "sum",

    "sell_volume": "sum",

    "delta": "sum"

})

ohlc.columns = [

    "open",
    "high",
    "low",
    "close",

    "buy_volume",
    "sell_volume",

    "delta"

]

ohlc = ohlc.dropna()

# =====================================
# TOTAL VOLUME
# =====================================

ohlc["volume"] = (

    ohlc["buy_volume"]

    +

    ohlc["sell_volume"]

)

# =====================================
# CANDLE TYPE
# =====================================

ohlc["candle_type"] = np.where(

    ohlc["close"] >= ohlc["open"],

    "bullish",

    "bearish"

)

# =====================================
# BODY
# =====================================

ohlc["body"] = (

    ohlc["close"]

    -

    ohlc["open"]

).abs()

# =====================================
# SPREAD
# =====================================

ohlc["spread"] = (

    ohlc["high"]

    -

    ohlc["low"]

)

# =====================================
# UPPER WICK
# =====================================

ohlc["upper_wick"] = (

    ohlc["high"]

    -

    ohlc[["open", "close"]].max(axis=1)

)

# =====================================
# LOWER WICK
# =====================================

ohlc["lower_wick"] = (

    ohlc[["open", "close"]].min(axis=1)

    -

    ohlc["low"]

)

# =====================================
# CLOSE POSITION
# =====================================

ohlc["close_position"] = (

    (

        ohlc["close"]

        -

        ohlc["low"]

    )

    /

    (

        ohlc["spread"]

        +

        0.000001

    )

)

# =====================================
# SPREAD RELATIVE CONTEXT
# =====================================

ohlc["spread_mean_20"] = (

    ohlc["spread"]

    .rolling(20)

    .mean()

)

ohlc["spread_std_20"] = (

    ohlc["spread"]

    .rolling(20)

    .std()

)

# =====================================
# VOLUME RELATIVE CONTEXT
# =====================================

ohlc["volume_mean_20"] = (

    ohlc["volume"]

    .rolling(20)

    .mean()

)

ohlc["volume_std_20"] = (

    ohlc["volume"]

    .rolling(20)

    .std()

)

# =====================================
# SPREAD RANK
# =====================================

ohlc["spread_zscore"] = (

    (

        ohlc["spread"]

        -

        ohlc["spread_mean_20"]

    )

    /

    (

        ohlc["spread_std_20"]

        +

        0.000001

    )

)

# =====================================
# VOLUME RANK
# =====================================

ohlc["volume_zscore"] = (

    (

        ohlc["volume"]

        -

        ohlc["volume_mean_20"]

    )

    /

    (

        ohlc["volume_std_20"]

        +

        0.000001

    )

)

# =====================================
# SAVE MEMORY
# =====================================

ohlc.to_parquet(
    "candle_structure_memory.parquet"
)

# =====================================
# DEBUG OUTPUT
# =====================================

print("=" * 50)

print("CANDLE STRUCTURE DEBUG")

print("=" * 50)

print()

print("TOTAL CANDLES:")

print(len(ohlc))

print()

print("LAST 5 CANDLES:")

debug_cols = [

    "open",
    "high",
    "low",
    "close",

    "candle_type",

    "body",
    "spread",

    "upper_wick",
    "lower_wick",

    "close_position",

    "volume",

    "spread_zscore",

    "volume_zscore"

]

print(

    ohlc[debug_cols]

    .tail()

)

print()

print("MEMORY SAVED:")

print("candle_structure_memory.parquet")

print()
