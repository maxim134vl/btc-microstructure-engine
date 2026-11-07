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

        signals.append(current)

signals = pd.DataFrame(signals)

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# CURRENT CANDLE ANALYSIS
# =====================================

bullish = (
    signals["close"]
    >
    signals["open"]
).mean()

bearish = (
    signals["close"]
    <
    signals["open"]
).mean()

avg_close_position = (
    signals["close_position"]
    .mean()
)

avg_spread = (
    signals["spread"]
    .mean()
)

print()
print(
    "BULLISH SIGNAL CANDLES:",
    round(bullish * 100, 2),
    "%"
)

print(
    "BEARISH SIGNAL CANDLES:",
    round(bearish * 100, 2),
    "%"
)

print()

print(
    "AVERAGE CLOSE POSITION:",
    round(avg_close_position, 2)
)

print(
    "AVERAGE SPREAD:",
    round(avg_spread, 2)
)

print()
