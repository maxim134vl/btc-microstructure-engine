import pandas as pd

# =====================================
# LOAD DATA
# =====================================

volume = pd.read_parquet(
    "historical_volume_cognition.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# MARKET REGIME
# =====================================

candles["regime"] = candles["close"].diff(20)

candles["regime"] = candles["regime"].apply(
    lambda x:
        "BULLISH"
        if x > 0
        else "BEARISH"
)

# =====================================
# SIGNAL FILTER
# =====================================

signal_indexes = []

for _, row in volume.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    current_idx = candles[
        candles["timestamp"] <= timestamp
    ].index

    if len(current_idx) == 0:
        continue

    idx = current_idx[-1]

    current = candles.iloc[idx]

    if (

        current["regime"] == "BULLISH"

        and

        row["unfinished_auction"] == True

        and

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

    ):

        signal_indexes.append(idx)

print()
print(
    "TOTAL SIGNALS:",
    len(signal_indexes)
)

# =====================================
# PRE VS POST VOLATILITY
# =====================================

pre_spreads = []
post_spreads = []

for idx in signal_indexes:

    pre = candles.iloc[
        max(0, idx - 5):idx
    ]

    post = candles.iloc[
        idx + 1:idx + 6
    ]

    if len(pre) < 5 or len(post) < 5:
        continue

    pre_spreads.append(
        pre["spread"].mean()
    )

    post_spreads.append(
        post["spread"].mean()
    )

pre_spreads = pd.Series(pre_spreads)
post_spreads = pd.Series(post_spreads)

print()
print(
    "AVERAGE PRE-SIGNAL SPREAD:",
    round(pre_spreads.mean(), 2)
)

print(
    "AVERAGE POST-SIGNAL SPREAD:",
    round(post_spreads.mean(), 2)
)

print()

delta = (
    post_spreads.mean()
    -
    pre_spreads.mean()
)

print(
    "VOLATILITY CHANGE:",
    round(delta, 2)
)

print()

