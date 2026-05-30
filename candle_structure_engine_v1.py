import pandas as pd
import numpy as np

from live_feed_paths import read_live_feed_history
from storage.path_registry import resolve_write

print("\nCANDLE STRUCTURE ENGINE STARTED\n")

# =====================================
# LOAD DATA — canonical live feed (not multi_exchange_flow)
# =====================================

feed = read_live_feed_history()

if len(feed) == 0:
    print("NO LIVE FEED DATA")
    print()
    raise SystemExit(1)

feed["timestamp"] = pd.to_datetime(feed["timestamp"])
feed = feed.sort_values("timestamp").drop_duplicates(subset=["timestamp"])

ohlc = feed.copy()

# =====================================
# DELTA / BUY-SELL SPLIT
# =====================================

if "taker_buy_volume" in ohlc.columns:
    ohlc["buy_volume"] = ohlc["taker_buy_volume"].fillna(0)
    ohlc["sell_volume"] = (ohlc["volume"] - ohlc["buy_volume"]).clip(lower=0)
else:
    body_share = (
        (ohlc["close"] - ohlc["open"]).abs()
        / (ohlc["high"] - ohlc["low"] + 0.000001)
    ).clip(0, 1)
    bullish = ohlc["close"] >= ohlc["open"]
    ohlc["buy_volume"] = np.where(
        bullish,
        ohlc["volume"] * (0.5 + 0.5 * body_share),
        ohlc["volume"] * (0.5 - 0.5 * body_share),
    )
    ohlc["sell_volume"] = ohlc["volume"] - ohlc["buy_volume"]

ohlc["delta"] = ohlc["buy_volume"] - ohlc["sell_volume"]

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

    .rolling(10)

    .mean()

)

ohlc["volume_std_20"] = (

    ohlc["volume"]

    .rolling(10)

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

ohlc = ohlc.reset_index(drop=True)

ohlc.to_parquet(
    resolve_write("candle_structure_memory.parquet")
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

print("TIMESTAMP RANGE:")

print(ohlc["timestamp"].min(), "->", ohlc["timestamp"].max())

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
