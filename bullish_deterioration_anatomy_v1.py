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
# METRICS
# =====================================

future_upper_wicks = []
future_lower_wicks = []

future_bodies = []
future_spreads = []

future_deltas = []

# =====================================
# ANALYSIS
# =====================================

for _, row in signals.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(5)

    if len(future) < 5:
        continue

    future_upper_wicks.append(
        future["upper_wick"].mean()
    )

    future_lower_wicks.append(
        future["lower_wick"].mean()
    )

    future_bodies.append(
        future["body"].mean()
    )

    future_spreads.append(
        future["spread"].mean()
    )

    future_deltas.append(
        future["delta"].mean()
    )

# =====================================
# RESULTS
# =====================================

print()
print("=" * 40)
print("FUTURE STRUCTURE")
print("=" * 40)

print()

print(
    "AVG UPPER WICK:",
    round(
        pd.Series(
            future_upper_wicks
        ).mean(),
        2
    )
)

print(
    "AVG LOWER WICK:",
    round(
        pd.Series(
            future_lower_wicks
        ).mean(),
        2
    )
)

print(
    "AVG BODY:",
    round(
        pd.Series(
            future_bodies
        ).mean(),
        2
    )
)

print(
    "AVG SPREAD:",
    round(
        pd.Series(
            future_spreads
        ).mean(),
        2
    )
)

print(
    "AVG DELTA:",
    round(
        pd.Series(
            future_deltas
        ).mean(),
        2
    )
)

print()
