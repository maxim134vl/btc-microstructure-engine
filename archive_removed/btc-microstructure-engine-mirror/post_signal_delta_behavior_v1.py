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
# PRE VS POST DELTA
# =====================================

pre_delta = []
post_delta = []

for idx in signal_indexes:

    pre = candles.iloc[
        max(0, idx - 5):idx
    ]

    post = candles.iloc[
        idx + 1:idx + 6
    ]

    if len(pre) < 5 or len(post) < 5:
        continue

    pre_delta.append(
        pre["delta"].mean()
    )

    post_delta.append(
        post["delta"].mean()
    )

pre_delta = pd.Series(pre_delta)
post_delta = pd.Series(post_delta)

print()
print(
    "AVERAGE PRE-SIGNAL DELTA:",
    round(pre_delta.mean(), 2)
)

print(
    "AVERAGE POST-SIGNAL DELTA:",
    round(post_delta.mean(), 2)
)

print()

delta_shift = (
    post_delta.mean()
    -
    pre_delta.mean()
)

print(
    "DELTA SHIFT:",
    round(delta_shift, 2)
)

print()
