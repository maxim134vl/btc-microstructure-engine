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
# FILTER
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

        current["regime"] == "BEARISH"

        and

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

        and

        row["unfinished_auction"] == True

    ):

        signals.append(idx)

print()
print(
    "TOTAL BEARISH SIGNALS:",
    len(signals)
)

# =====================================
# TEST
# =====================================

horizons = [
    5,
    10,
    20
]

for horizon in horizons:

    results = []

    for idx in signals:

        future = candles.iloc[
            idx + 1:
            idx + horizon + 1
        ]

        if len(future) < horizon:
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

    if len(results) == 0:
        continue

    down_rate = (
        results < 0
    ).mean()

    print()
    print(
        "=" * 40
    )

    print(
        "HORIZON:",
        horizon
    )

    print(
        "DOWN RATE:",
        round(down_rate * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
