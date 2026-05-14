import pandas as pd
import numpy as np

print("\nLIVE VOLUME FLOW ENGINE STARTED\n")

# =====================================
# LOAD FEED
# =====================================

df = pd.read_parquet(
    "live_market_feed.parquet"
)

df = df.sort_values(
    "timestamp"
).copy()

# =====================================
# FEATURES
# =====================================

df["spread"] = (

    df["high"]
    -
    df["low"]

)

df["price_change"] = (

    df["close"]
    -
    df["open"]

)

# =====================================
# PARTICIPATION
# =====================================

df["volume_mean_20"] = (

    df["volume"]

    .rolling(20)

    .mean()

)

df["volume_ratio"] = (

    df["volume"]
    /
    df["volume_mean_20"]

)

# =====================================
# SPREAD EXPANSION
# =====================================

df["spread_mean_20"] = (

    df["spread"]

    .rolling(20)

    .mean()

)

df["spread_ratio"] = (

    df["spread"]
    /
    df["spread_mean_20"]

)

# =====================================
# FLOW STATE
# =====================================

flow_states = []

for i in range(len(df)):

    row = df.iloc[i]

    volume_ratio = row["volume_ratio"]

    spread_ratio = row["spread_ratio"]

    change = abs(
        row["price_change"]
    )

    state = "neutral"

    # =====================================
    # AGGRESSIVE EXPANSION
    # =====================================

    if (

        volume_ratio > 1.8

        and

        spread_ratio > 1.5

    ):

        state = (
            "aggressive_expansion"
        )

    # =====================================
    # COMPRESSION
    # =====================================

    elif (

        volume_ratio < 0.8

        and

        spread_ratio < 0.8

    ):

        state = (
            "compression"
        )

    # =====================================
    # PASSIVE PULLBACK
    # =====================================

    elif (

        volume_ratio < 1

        and

        spread_ratio < 1

        and

        change < (
            row["spread"] * 0.3
        )

    ):

        state = (
            "passive_pullback"
        )

    # =====================================
    # EXHAUSTION
    # =====================================

    elif (

        volume_ratio > 1.5

        and

        spread_ratio < 0.8

    ):

        state = (
            "exhaustion"
        )

    # =====================================
    # FAILED EXPANSION
    # =====================================

    elif (

        spread_ratio > 1.5

        and

        volume_ratio < 1

    ):

        state = (
            "failed_expansion"
        )

    flow_states.append(
        state
    )

# =====================================
# SAVE
# =====================================

df["flow_state"] = flow_states

memory = df[

    [

        "timestamp",

        "volume",

        "spread",

        "price_change",

        "volume_ratio",

        "spread_ratio",

        "flow_state"

    ]

]

memory.to_parquet(
    "live_volume_flow_memory.parquet",
    index=False
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("FLOW DISTRIBUTION")

print("=" * 50)

print()

print(
    memory[
        "flow_state"
    ].value_counts()
)

print()

print(
    memory.tail(30)
)

print()

print("MEMORY SAVED:")

print(
    "live_volume_flow_memory.parquet"
)

print()
