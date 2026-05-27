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
# BASELINE
# =====================================

baseline_results = []

for i in range(len(candles) - 10):

    start_price = candles.iloc[i]["close"]

    end_price = candles.iloc[i + 10]["close"]

    move = (
        end_price
        -
        start_price
    )

    baseline_results.append(move)

baseline_results = pd.Series(
    baseline_results
)

baseline_down = (
    baseline_results < 0
).mean()

print()
print(
    "BASELINE DOWN RATE:",
    round(baseline_down * 100, 2),
    "%"
)

# =====================================
# SIGNAL FILTER
# =====================================

filtered_rows = []

for _, row in volume.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    current = candles[
        candles["timestamp"] <= timestamp
    ]

    if len(current) == 0:
        continue

    regime = current.iloc[-1]["regime"]

    if (

        regime == "BULLISH"

        and

        row["unfinished_auction"] == True

        and

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

    ):

        filtered_rows.append(row)

filtered = pd.DataFrame(filtered_rows)

print()
print(
    "TOTAL SIGNAL STATES:",
    len(filtered)
)

# =====================================
# SIGNAL TEST
# =====================================

results = []

for _, row in filtered.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(10)

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

signal_down = (
    results < 0
).mean()

edge = (
    signal_down
    -
    baseline_down
) * 100

print()
print(
    "SIGNAL DOWN RATE:",
    round(signal_down * 100, 2),
    "%"
)

print(
    "EDGE VS BASELINE:",
    round(edge, 2),
    "%"
)

print()
print(
    "AVERAGE MOVE:",
    round(results.mean(), 2)
)

print()
