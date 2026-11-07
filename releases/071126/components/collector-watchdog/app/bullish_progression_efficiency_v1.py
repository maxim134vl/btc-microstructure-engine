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
# EFFICIENCY
# =====================================

progression = []
rotation = []

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

    directional_move = (

        future.iloc[-1]["close"]

        -

        future.iloc[0]["close"]

    )

    total_spread = future[
        "spread"
    ].sum()

    progression.append(
        directional_move
    )

    rotation.append(
        total_spread
    )

# =====================================
# RESULTS
# =====================================

progression = pd.Series(
    progression
)

rotation = pd.Series(
    rotation
)

efficiency = (
    progression.abs()
    /
    rotation
)

print()
print("=" * 40)
print("PROGRESSION")
print("=" * 40)

print()

print(
    "AVG DIRECTIONAL MOVE:",
    round(
        progression.mean(),
        2
    )
)

print(
    "AVG ROTATION:",
    round(
        rotation.mean(),
        2
    )
)

print(
    "AVG EFFICIENCY:",
    round(
        efficiency.mean(),
        4
    )
)

print()
