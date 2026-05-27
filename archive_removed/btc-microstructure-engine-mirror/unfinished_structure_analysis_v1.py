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

        row["participation_state"]
        ==
        "HIGH_PARTICIPATION"

        and

        row["unfinished_auction"] == True

    ):

        signals.append(current)

signals = pd.DataFrame(signals)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# STRUCTURE ANALYSIS
# =====================================

print()
print(
    "=" * 40
)

print(
    "AVERAGE BODY:"
)

print(
    round(signals["body"].mean(), 2)
)

print()

print(
    "AVERAGE UPPER WICK:"
)

print(
    round(signals["upper_wick"].mean(), 2)
)

print()

print(
    "AVERAGE LOWER WICK:"
)

print(
    round(signals["lower_wick"].mean(), 2)
)

print()

print(
    "AVERAGE CLOSE POSITION:"
)

print(
    round(signals["close_position"].mean(), 2)
)

print()

print(
    "AVERAGE SPREAD:"
)

print(
    round(signals["spread"].mean(), 2)
)

print()

