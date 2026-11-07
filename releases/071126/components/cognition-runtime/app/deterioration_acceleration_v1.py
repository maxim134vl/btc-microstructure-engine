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
# ACCELERATION TEST
# =====================================

phase_1 = []
phase_2 = []

for idx in signals:

    if idx + 6 >= len(candles):
        continue

    close_0 = candles.iloc[idx]["close"]

    close_3 = candles.iloc[idx + 3]["close"]

    close_6 = candles.iloc[idx + 6]["close"]

    move_1 = close_3 - close_0

    move_2 = close_6 - close_3

    phase_1.append(move_1)

    phase_2.append(move_2)

phase_1 = pd.Series(phase_1)
phase_2 = pd.Series(phase_2)

print()
print(
    "PHASE 1 AVG MOVE:",
    round(phase_1.mean(), 2)
)

print(
    "PHASE 2 AVG MOVE:",
    round(phase_2.mean(), 2)
)

print()

print(
    "PHASE 1 DOWN RATE:",
    round(
        (phase_1 < 0).mean() * 100,
        2
    ),
    "%"
)

print(
    "PHASE 2 DOWN RATE:",
    round(
        (phase_2 < 0).mean() * 100,
        2
    ),
    "%"
)

print()
