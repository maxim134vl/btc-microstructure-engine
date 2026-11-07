import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# LOWER WICK THRESHOLD
# =====================================

wick_threshold = candles[
    "lower_wick"
].quantile(0.8)

print()
print(
    "LOWER WICK THRESHOLD:",
    round(wick_threshold, 2)
)

# =====================================
# SIGNALS
# =====================================

signals = candles[

    candles["lower_wick"]
    >
    wick_threshold

].copy()

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# FUTURE TEST
# =====================================

results = []

for _, row in signals.iterrows():

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

print()

if len(results) > 0:

    up_rate = (
        results > 0
    ).mean()

    print(
        "UP RATE:",
        round(up_rate * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
