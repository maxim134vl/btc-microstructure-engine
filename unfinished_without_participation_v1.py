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
# FILTER
# =====================================

signals = []

for _, row in volume.iterrows():

    if (

        row["unfinished_auction"] == True

        and

        row["participation_state"]
        !=
        "HIGH_PARTICIPATION"

    ):

        timestamp = pd.to_datetime(
            row["timestamp"]
        )

        idx = candles[
            candles["timestamp"] <= timestamp
        ].index

        if len(idx) == 0:
            continue

        signals.append(idx[-1])

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
