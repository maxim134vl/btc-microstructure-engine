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
# THRESHOLDS
# =====================================

volume_threshold = candles["volume"].quantile(
    0.9
)

delta_threshold = candles["delta"].abs().quantile(
    0.9
)

# =====================================
# FILTER
# =====================================

signals = []

for _, row in volume.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    current = candles[
        candles["timestamp"] <= timestamp
    ]

    if len(current) == 0:
        continue

    current = current.iloc[-1]

    if (

        row["unfinished_auction"] == True

        and

        current["volume"]
        >
        volume_threshold

        and

        abs(current["delta"])
        >
        delta_threshold

    ):

        idx = candles[
            candles["timestamp"]
            ==
            current["timestamp"]
        ].index[0]

        signals.append(idx)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# CONTINUATION ANALYSIS
# =====================================

continuation_moves = []
rejection_moves = []

for idx in signals:

    if idx + 5 >= len(candles):
        continue

    future = candles.iloc[
        idx + 1:
        idx + 6
    ]

    current_close = candles.iloc[idx]["close"]

    max_up = (
        future["high"].max()
        -
        current_close
    )

    final_move = (
        future.iloc[-1]["close"]
        -
        current_close
    )

    continuation_moves.append(max_up)

    rejection_moves.append(
        final_move
    )

continuation_moves = pd.Series(
    continuation_moves
)

rejection_moves = pd.Series(
    rejection_moves
)

print()
print(
    "AVERAGE MAX CONTINUATION:",
    round(
        continuation_moves.mean(),
        2
    )
)

print(
    "AVERAGE FINAL MOVE:",
    round(
        rejection_moves.mean(),
        2
    )
)

print()

continuation_efficiency = (

    rejection_moves.mean()

    /

    (
        continuation_moves.mean()
        + 1e-9
    )

)

print(
    "CONTINUATION EFFICIENCY:",
    round(
        continuation_efficiency,
        2
    )
)

print()
