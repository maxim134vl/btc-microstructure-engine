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
# FIRST 3 CANDLES
# =====================================

first_moves = []
second_moves = []
third_moves = []

for idx in signals:

    if idx + 3 >= len(candles):
        continue

    current_close = candles.iloc[idx]["close"]

    c1 = candles.iloc[idx + 1]["close"]
    c2 = candles.iloc[idx + 2]["close"]
    c3 = candles.iloc[idx + 3]["close"]

    first_moves.append(
        c1 - current_close
    )

    second_moves.append(
        c2 - current_close
    )

    third_moves.append(
        c3 - current_close
    )

# =====================================
# RESULTS
# =====================================

for name, moves in [

    ("FIRST", first_moves),
    ("SECOND", second_moves),
    ("THIRD", third_moves)

]:

    moves = pd.Series(moves)

    print()
    print(
        "=" * 40
    )

    print(
        name,
        "CANDLE"
    )

    print(
        "DOWN RATE:",
        round(
            (moves < 0).mean() * 100,
            2
        ),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(
            moves.mean(),
            2
        )
    )

print()
