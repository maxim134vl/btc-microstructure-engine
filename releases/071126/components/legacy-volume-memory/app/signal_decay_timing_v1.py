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

    current = candles[
        candles["timestamp"] <= timestamp
    ]

    if len(current) == 0:
        continue

    current = current.iloc[-1]

    if (

        current["regime"] == "BULLISH"

        and

        row["unfinished_auction"] == True

        and

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

    ):

        signals.append(timestamp)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# STEP-BY-STEP DECAY
# =====================================

for step in range(1, 11):

    results = []

    for timestamp in signals:

        future = candles[
            candles["timestamp"] > timestamp
        ].head(step)

        if len(future) < step:
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

    print(
        "STEP",
        step,
        "| DOWN:",
        round(down_rate * 100, 2),
        "%",
        "| AVG MOVE:",
        round(results.mean(), 2)
    )

print()
