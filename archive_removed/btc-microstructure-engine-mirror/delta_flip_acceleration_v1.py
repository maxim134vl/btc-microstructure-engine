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
# DELTA FLIP TEST
# =====================================

flip_results = []
non_flip_results = []

for idx in signals:

    if idx + 6 >= len(candles):
        continue

    signal_delta = candles.iloc[idx]["delta"]

    future_delta = candles.iloc[idx + 2]["delta"]

    close_0 = candles.iloc[idx]["close"]

    close_6 = candles.iloc[idx + 6]["close"]

    move = (
        close_6
        -
        close_0
    )

    flipped = (
        signal_delta * future_delta
    ) < 0

    if flipped:

        flip_results.append(move)

    else:

        non_flip_results.append(move)

flip_results = pd.Series(flip_results)
non_flip_results = pd.Series(non_flip_results)

print()
print(
    "=" * 40
)

print(
    "DELTA FLIP STATES:",
    len(flip_results)
)

if len(flip_results) > 0:

    print(
        "AVG MOVE:",
        round(flip_results.mean(), 2)
    )

    print(
        "DOWN RATE:",
        round(
            (flip_results < 0).mean() * 100,
            2
        ),
        "%"
    )

print()
print(
    "=" * 40
)

print(
    "NO FLIP STATES:",
    len(non_flip_results)
)

if len(non_flip_results) > 0:

    print(
        "AVG MOVE:",
        round(non_flip_results.mean(), 2)
    )

    print(
        "DOWN RATE:",
        round(
            (non_flip_results < 0).mean() * 100,
            2
        ),
        "%"
    )

print()
