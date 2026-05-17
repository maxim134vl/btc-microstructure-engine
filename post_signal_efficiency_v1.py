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
# EFFICIENCY
# =====================================

candles["efficiency"] = (

    candles["body"].abs()

    /

    (
        candles["delta"].abs()
        + 1e-9
    )

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
# PRE VS POST EFFICIENCY
# =====================================

pre_eff = []
post_eff = []

for idx in signals:

    pre = candles.iloc[
        max(0, idx - 3):idx
    ]

    post = candles.iloc[
        idx + 1:idx + 4
    ]

    if len(pre) < 3 or len(post) < 3:
        continue

    pre_eff.append(
        pre["efficiency"].mean()
    )

    post_eff.append(
        post["efficiency"].mean()
    )

pre_eff = pd.Series(pre_eff)
post_eff = pd.Series(post_eff)

print()
print(
    "PRE EFFICIENCY:",
    round(pre_eff.mean(), 6)
)

print(
    "POST EFFICIENCY:",
    round(post_eff.mean(), 6)
)

print()

print(
    "EFFICIENCY CHANGE:",
    round(
        post_eff.mean()
        -
        pre_eff.mean(),
        6
    )
)

print()
