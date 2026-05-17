import pandas as pd
import numpy as np

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# EFFICIENCY
# =====================================

candles["efficiency"] = np.where(

    candles["delta"].abs() > 0,

    candles["body"].abs()

    /

    candles["delta"].abs(),

    0

)

# =====================================
# THRESHOLDS
# =====================================

volume_threshold = candles["volume"].quantile(
    0.7
)

positive_delta_threshold = candles[
    candles["delta"] > 0
]["delta"].quantile(0.7)

efficiency_threshold = candles[
    candles["efficiency"] > 0
]["efficiency"].quantile(0.7)

print()
print(
    "VOLUME THRESHOLD:",
    round(volume_threshold, 2)
)

print(
    "POSITIVE DELTA THRESHOLD:",
    round(positive_delta_threshold, 2)
)

print(
    "EFFICIENCY THRESHOLD:",
    round(efficiency_threshold, 4)
)

# =====================================
# SIGNALS
# =====================================

signals = candles[

    (candles["volume"] > volume_threshold)

    &

    (candles["delta"] > positive_delta_threshold)

    &

    (candles["efficiency"] > efficiency_threshold)

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
