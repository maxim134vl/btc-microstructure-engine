import pandas as pd
import numpy as np

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

positive_delta_threshold = candles[
    candles["delta"] > 0
]["delta"].quantile(0.9)

# =====================================
# EFFICIENCY
# =====================================

candles["efficiency"] = np.where(

    candles["delta"].abs() > 0,

    candles["body"].abs()

    /

    candles["delta"].abs(),

    0
)

# =====================================
# FILTER
# =====================================

signal_eff = []
baseline_eff = []

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

    eff = current["efficiency"]

    if current["delta"] > 0:

        baseline_eff.append(eff)

    if (

        row["unfinished_auction"] == True

        and

        current["volume"]
        >
        volume_threshold

        and

        current["delta"]
        >
        positive_delta_threshold

    ):

        signal_eff.append(eff)

signal_eff = pd.Series(signal_eff)
baseline_eff = pd.Series(baseline_eff)

print()
print(
    "TOTAL SIGNALS:",
    len(signal_eff)
)

print()

print(
    "SIGNAL EFFICIENCY:",
    round(signal_eff.mean(), 6)
)

print(
    "BASELINE POSITIVE EFFICIENCY:",
    round(baseline_eff.mean(), 6)
)

print()

ratio = (

    signal_eff.mean()

    /

    (
        baseline_eff.mean()
        + 1e-9
    )

)

print(
    "EFFICIENCY RATIO:",
    round(ratio, 4)
)

print()
