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
# THRESHOLDS
# =====================================

volume_threshold = candles["volume"].quantile(
    0.9
)

delta_threshold = candles["delta"].abs().quantile(
    0.9
)

# =====================================
# FILTER
# =====================================

signals = []

for _, row in volume.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    current = candles[
        candles["timestamp"] <= timestamp
    ]

    if len(current) == 0:
        continue

    current = current.iloc[-1]

    if (

        row["unfinished_auction"] == True

        and

        current["volume"]
        >
        volume_threshold

        and

        abs(current["delta"])
        >
        delta_threshold

    ):

        idx = candles[
            candles["timestamp"]
            ==
            current["timestamp"]
        ].index[0]

        signals.append(idx)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# PRE VS POST WICKS
# =====================================

pre_upper = []
post_upper = []

pre_lower = []
post_lower = []

for idx in signals:

    pre = candles.iloc[
        max(0, idx - 3):idx
    ]

    post = candles.iloc[
        idx + 1:idx + 4
    ]

    if len(pre) < 3 or len(post) < 3:
        continue

    pre_upper.append(
        pre["upper_wick"].mean()
    )

    post_upper.append(
        post["upper_wick"].mean()
    )

    pre_lower.append(
        pre["lower_wick"].mean()
    )

    post_lower.append(
        post["lower_wick"].mean()
    )

pre_upper = pd.Series(pre_upper)
post_upper = pd.Series(post_upper)

pre_lower = pd.Series(pre_lower)
post_lower = pd.Series(post_lower)

print()
print(
    "PRE UPPER WICK:",
    round(pre_upper.mean(), 2)
)

print(
    "POST UPPER WICK:",
    round(post_upper.mean(), 2)
)

print()

print(
    "PRE LOWER WICK:",
    round(pre_lower.mean(), 2)
)

print(
    "POST LOWER WICK:",
    round(post_lower.mean(), 2)
)

print()
