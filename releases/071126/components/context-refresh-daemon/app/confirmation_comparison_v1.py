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
# RAW SIGNALS
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
    "TOTAL RAW SIGNALS:",
    len(signals)
)

# =====================================
# RAW PERFORMANCE
# =====================================

raw_results = []

for idx in signals:

    future = candles.iloc[
        idx + 1:
        idx + 11
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

    raw_results.append(move)

raw_results = pd.Series(raw_results)

raw_down = (
    raw_results < 0
).mean()

# =====================================
# CONFIRMED PERFORMANCE
# =====================================

confirmed_results = []

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

    if not bearish:
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

    confirmed_results.append(move)

confirmed_results = pd.Series(
    confirmed_results
)

confirmed_down = (
    confirmed_results < 0
).mean()

# =====================================
# RESULTS
# =====================================

print()
print(
    "=" * 40
)

print(
    "RAW SIGNAL"
)

print(
    "DOWN RATE:",
    round(raw_down * 100, 2),
    "%"
)

print(
    "AVERAGE MOVE:",
    round(raw_results.mean(), 2)
)

print()

print(
    "=" * 40
)

print(
    "CONFIRMED SIGNAL"
)

print(
    "DOWN RATE:",
    round(confirmed_down * 100, 2),
    "%"
)

print(
    "AVERAGE MOVE:",
    round(confirmed_results.mean(), 2)
)

print()
