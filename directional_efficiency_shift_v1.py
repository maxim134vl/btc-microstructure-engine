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
# DIRECTIONAL EFFICIENCY
# =====================================

candles["directional_efficiency"] = np.where(

    candles["delta"] != 0,

    candles["body"] / candles["delta"],

    0
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
# POST SIGNAL ANALYSIS
# =====================================

positive_eff = []
negative_eff = []

for idx in signals:

    future = candles.iloc[
        idx + 1:
        idx + 6
    ]

    if len(future) < 5:
        continue

    pos = future[
        future["delta"] > 0
    ]

    neg = future[
        future["delta"] < 0
    ]

    if len(pos) > 0:

        positive_eff.append(
            pos["directional_efficiency"]
            .mean()
        )

    if len(neg) > 0:

        negative_eff.append(
            neg["directional_efficiency"]
            .mean()
        )

positive_eff = pd.Series(positive_eff)
negative_eff = pd.Series(negative_eff)

print()
print(
    "POSITIVE DELTA EFFICIENCY:",
    round(positive_eff.mean(), 6)
)

print(
    "NEGATIVE DELTA EFFICIENCY:",
    round(negative_eff.mean(), 6)
)

print()
