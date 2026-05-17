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
# MARKET REGIME
# =====================================

candles["regime"] = candles["close"].diff(20)

candles["regime"] = candles["regime"].apply(
    lambda x:
        "BULLISH"
        if x > 0
        else "BEARISH"
)

# =====================================
# SIGNAL FILTER
# =====================================

signals = []

for _, row in volume.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    current_idx = candles[
        candles["timestamp"] <= timestamp
    ].index

    if len(current_idx) == 0:
        continue

    idx = current_idx[-1]

    current = candles.iloc[idx]

    if (

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

        and

        row["unfinished_auction"] == True

    ):

        signals.append(idx)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# FUTURE RANGE TEST
# =====================================

up_moves = []
down_moves = []

for idx in signals:

    future = candles.iloc[
        idx + 1:
        idx + 11
    ]

    if len(future) < 10:
        continue

    current_close = candles.iloc[idx]["close"]

    max_up = (
        future["high"].max()
        -
        current_close
    )

    max_down = (
        current_close
        -
        future["low"].min()
    )

    up_moves.append(max_up)

    down_moves.append(max_down)

up_moves = pd.Series(up_moves)
down_moves = pd.Series(down_moves)

print()
print(
    "AVERAGE MAX UP MOVE:",
    round(up_moves.mean(), 2)
)

print(
    "AVERAGE MAX DOWN MOVE:",
    round(down_moves.mean(), 2)
)

print()

print(
    "DOWN DOMINANCE RATIO:",
    round(
        down_moves.mean()
        /
        (
            up_moves.mean()
            + 1e-9
        ),
        2
    )
)

print()
