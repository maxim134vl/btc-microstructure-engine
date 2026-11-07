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

    regime = current.iloc[-1]["regime"]

    if (

        regime == "BULLISH"

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
# PRE-SIGNAL ANALYSIS
# =====================================

results = []

for timestamp in signals:

    history = candles[
        candles["timestamp"] < timestamp
    ].tail(10)

    if len(history) < 10:
        continue

    start_price = history.iloc[0]["close"]

    end_price = history.iloc[-1]["close"]

    move = (
        end_price
        -
        start_price
    )

    results.append(move)

results = pd.Series(results)

print()
print(
    "AVERAGE PRE-SIGNAL MOVE:",
    round(results.mean(), 2)
)

print()
print(
    "UPTREND BEFORE SIGNAL:",
    round((results > 0).mean() * 100, 2),
    "%"
)

print(
    "DOWNTREND BEFORE SIGNAL:",
    round((results < 0).mean() * 100, 2),
    "%"
)

print()
