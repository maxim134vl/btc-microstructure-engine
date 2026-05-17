import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# THRESHOLDS
# =====================================

lower_wick_threshold = candles[
    "lower_wick"
].quantile(0.8)

upper_wick_threshold = candles[
    "upper_wick"
].quantile(0.5)

body_threshold = candles[
    "body"
].quantile(0.6)

volume_threshold = candles[
    "volume"
].quantile(0.7)

delta_threshold = candles[
    "delta"
].quantile(0.7)

print()
print(
    "LOWER WICK:",
    round(lower_wick_threshold, 2)
)

print(
    "UPPER WICK:",
    round(upper_wick_threshold, 2)
)

print(
    "BODY:",
    round(body_threshold, 2)
)

# =====================================
# SIGNALS
# =====================================

signals = candles[

    (candles["lower_wick"]
     > lower_wick_threshold)

    &

    (candles["upper_wick"]
     < upper_wick_threshold)

    &

    (candles["body"]
     > body_threshold)

    &

    (candles["volume"]
     < volume_threshold)

    &

    (candles["delta"]
     < delta_threshold)

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
