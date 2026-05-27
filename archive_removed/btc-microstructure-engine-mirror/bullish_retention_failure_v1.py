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
# RETENTION
# =====================================

max_up_moves = []
final_moves = []

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

    max_up_moves.append(
        max_up
    )

    final_moves.append(
        final_move
    )

# =====================================
# RESULTS
# =====================================

max_up_moves = pd.Series(
    max_up_moves
)

final_moves = pd.Series(
    final_moves
)

retention_ratio = (
    final_moves
    /
    max_up_moves.replace(0, 1)
)

print()
print("=" * 40)
print("RETENTION")
print("=" * 40)

print()

print(
    "AVG MAX UP MOVE:",
    round(
        max_up_moves.mean(),
        2
    )
)

print(
    "AVG FINAL MOVE:",
    round(
        final_moves.mean(),
        2
    )
)

print(
    "AVG RETENTION:",
    round(
        retention_ratio.mean(),
        4
    )
)

print()
