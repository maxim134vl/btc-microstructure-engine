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

delta_threshold = candles["delta"].abs().quantile(
    0.9
)

# =====================================
# EFFICIENCY
# =====================================

candles["delta_price_efficiency"] = np.where(

    candles["delta"].abs() > 0,

    candles["body"].abs()

    /

    candles["delta"].abs(),

    0
)

# =====================================
# FILTER
# =====================================

signal_efficiency = []
baseline_efficiency = []

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

    eff = current["delta_price_efficiency"]

    baseline_efficiency.append(eff)

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

        signal_efficiency.append(eff)

signal_efficiency = pd.Series(
    signal_efficiency
)

baseline_efficiency = pd.Series(
    baseline_efficiency
)

print()
print(
    "TOTAL SIGNAL STATES:",
    len(signal_efficiency)
)

print()

print(
    "SIGNAL EFFICIENCY:",
    round(
        signal_efficiency.mean(),
        6
    )
)

print(
    "BASELINE EFFICIENCY:",
    round(
        baseline_efficiency.mean(),
        6
    )
)

print()

ratio = (

    signal_efficiency.mean()

    /

    (
        baseline_efficiency.mean()
        + 1e-9
    )

)

print(
    "EFFICIENCY RATIO:",
    round(ratio, 2)
)

print()
