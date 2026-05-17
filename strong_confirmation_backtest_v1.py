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
# SIGNALS
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

        current["regime"] == "BULLISH"

        and

        row["unfinished_auction"] == True

        and

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

    ):

        signals.append(idx)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# STRONG CONFIRMATION
# =====================================

results = []

for idx in signals:

    confirm_idx = idx + 1

    if confirm_idx >= len(candles):
        continue

    confirm = candles.iloc[confirm_idx]

    bearish = (
        confirm["close"]
        <
        confirm["open"]
    )

    weak_close = (
        confirm["close_position"]
        < 0.4
    )

    if not (
        bearish
        and
        weak_close
    ):
        continue

    future = candles.iloc[
        confirm_idx + 1:
        confirm_idx + 11
    ]

    if len(future) < 10:
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

print()
print(
    "TOTAL STRONG CONFIRMATIONS:",
    len(results)
)

if len(results) > 0:

    down_rate = (
        results < 0
    ).mean()

    print()
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
