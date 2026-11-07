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
# LOCAL EXTREMES
# =====================================

candles["rolling_high"] = (

    candles["high"]
    .rolling(20)
    .max()

)

candles["distance_from_high"] = (

    candles["rolling_high"]

    -

    candles["close"]

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
# EXTREME ANALYSIS
# =====================================

near_high = signals[
    signals["distance_from_high"]
    <
    (
        signals["rolling_high"]
        * 0.002
    )
]

print()
print(
    "SIGNALS NEAR LOCAL HIGHS:",
    len(near_high)
)

print(
    "PERCENT NEAR HIGHS:",
    round(
        len(near_high)
        /
        len(signals)
        * 100,
        2
    ),
    "%"
)

print()
