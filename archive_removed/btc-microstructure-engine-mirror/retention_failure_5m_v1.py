import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory_5m.parquet"
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
# RETENTION ANALYSIS
# =====================================

max_up_moves = []
final_moves = []

retention_ratios = []

# =====================================
# ANALYSIS
# =====================================

for _, row in signals.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(20)

    if len(future) < 20:
        continue

    start_price = future.iloc[0]["close"]

    max_up = (

        future["high"].max()

        -
        start_price

    )

    final_move = (

        future.iloc[-1]["close"]

        -
        start_price

    )

    retention = (
        final_move
        /
        max(max_up, 1)
    )

    max_up_moves.append(
        max_up
    )

    final_moves.append(
        final_move
    )

    retention_ratios.append(
        retention
    )

# =====================================
# RESULTS
# =====================================

print()
print("=" * 40)
print("RETENTION RESULTS")
print("=" * 40)

print()

print(
    "AVG MAX UP MOVE:",
    round(
        pd.Series(
            max_up_moves
        ).mean(),
        2
    )
)

print(
    "AVG FINAL MOVE:",
    round(
        pd.Series(
            final_moves
        ).mean(),
        2
    )
)

print(
    "AVG RETENTION:",
    round(
        pd.Series(
            retention_ratios
        ).mean(),
        4
    )
)

print()
