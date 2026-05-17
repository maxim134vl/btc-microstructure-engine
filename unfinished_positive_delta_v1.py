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
# POSITIVE DELTA THRESHOLD
# =====================================

positive_threshold = candles[
    candles["delta"] > 0
]["delta"].quantile(0.9)

print()
print(
    "POSITIVE DELTA THRESHOLD:",
    round(positive_threshold, 2)
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

        current["delta"]
        >
        positive_threshold

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
# TEST
# =====================================

results = []

for idx in signals:

    future = candles.iloc[
        idx + 1:
        idx + 11
    ]

    if len(future) < 10:
        continue

    start_price = future.iloc[0]["close"]

    end_price = future.iloc[-1]["close"]

    move = (
        end_price
        -
        start_price
    )

    results.append(move)

results = pd.Series(results)

print()

down_rate = (
    results < 0
).mean()

print(
    "DOWN RATE:",
    round(down_rate * 100, 2),
    "%"
)

print(
    "AVERAGE MOVE:",
    round(results.mean(), 2)
)

print()
