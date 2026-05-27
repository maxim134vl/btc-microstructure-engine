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
# FLIP ANALYSIS
# =====================================

flip_counts = []

# =====================================
# ANALYSIS
# =====================================

for _, row in signals.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(10)

    if len(future) < 10:
        continue

    deltas = future["delta"].tolist()

    flips = 0

    for i in range(1, len(deltas)):

        previous = deltas[i - 1]
        current = deltas[i]

        if (
            previous > 0
            and current < 0
        ) or (
            previous < 0
            and current > 0
        ):

            flips += 1

    flip_counts.append(flips)

# =====================================
# RESULTS
# =====================================

flip_counts = pd.Series(
    flip_counts
)

print()
print("=" * 40)
print("DIRECTIONAL FLIPS")
print("=" * 40)

print()

print(
    "AVG FLIPS:",
    round(
        flip_counts.mean(),
        2
    )
)

print(
    "MAX FLIPS:",
    int(
        flip_counts.max()
    )
)

print(
    "MIN FLIPS:",
    int(
        flip_counts.min()
    )
)

print()
