import pandas as pd
import numpy as np

print("\nVOLATILITY ADAPTIVE ENGINE STARTED\n")

# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    "live_market_feed.parquet"
)

feed = feed.sort_values(
    "timestamp"
)

feed = feed.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

feed = feed.reset_index(
    drop=True
)

# =====================================
# LOAD BELIEFS
# =====================================

beliefs = pd.read_parquet(
    "live_recursive_beliefs.parquet"
)

# =====================================
# VOLATILITY
# =====================================

feed["spread"] = (

    feed["high"]
    -
    feed["low"]

)

feed["volatility_mean"] = (

    feed["spread"]

    .rolling(50)

    .mean()

)

feed["volatility_ratio"] = (

    feed["spread"]
    /
    feed["volatility_mean"]

)

# =====================================
# CURRENT VOLATILITY
# =====================================

current_volatility = float(

    feed.iloc[-1][
        "volatility_ratio"
    ]

)

# =====================================
# VOL REGIME
# =====================================

volatility_regime = (
    "normal_volatility"
)

if current_volatility > 1.5:

    volatility_regime = (
        "high_volatility"
    )

elif current_volatility < 0.7:

    volatility_regime = (
        "low_volatility"
    )

# =====================================
# STORAGE
# =====================================

adaptive_rows = []

# =====================================
# LOOP BELIEFS
# =====================================

for _, row in beliefs.iterrows():

    interaction = row[
        "interaction_type"
    ]

    weight = float(
        row["adaptive_weight"]
    )

    adjusted_weight = weight

    # =====================================
    # VOLATILITY ADAPTATION
    # =====================================

    # compression weaker in high vol

    if (

        interaction
        ==
        "compression_inside_liquidity"

        and

        volatility_regime
        ==
        "high_volatility"

    ):

        adjusted_weight = (
            weight * 0.8
        )

    # exhaustion stronger in high vol

    elif (

        interaction
        ==
        "exhaustion_at_liquidity"

        and

        volatility_regime
        ==
        "high_volatility"

    ):

        adjusted_weight = (
            weight * 1.2
        )

    # failed breakout stronger in low vol

    elif (

        interaction
        ==
        "failed_breakout_behavior"

        and

        volatility_regime
        ==
        "low_volatility"

    ):

        adjusted_weight = (
            weight * 1.15
        )

    # distribution stronger in high vol

    elif (

        interaction
        ==
        "expansion_into_distribution"

        and

        volatility_regime
        ==
        "high_volatility"

    ):

        adjusted_weight = (
            weight * 1.1
        )

    adjusted_weight = round(
        adjusted_weight,
        4
    )

    # =====================================
    # SAVE
    # =====================================

    adaptive_rows.append({

        "interaction_type":
            interaction,

        "base_weight":
            weight,

        "volatility_regime":
            volatility_regime,

        "volatility_ratio":
            round(
                current_volatility,
                4
            ),

        "adjusted_weight":
            adjusted_weight

    })

# =====================================
# BUILD DF
# =====================================

adaptive_df = pd.DataFrame(
    adaptive_rows
)

# =====================================
# SAVE
# =====================================

adaptive_df.to_parquet(

    "volatility_adaptive_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("VOLATILITY REGIME")

print("=" * 50)

print()

print(
    volatility_regime
)

print()

print(
    f"VOL RATIO: {round(current_volatility,4)}"
)

print()

print("=" * 50)

print("VOLATILITY ADAPTATION")

print("=" * 50)

print()

print(
    adaptive_df
)

print()

print("MEMORY SAVED:")

print(
    "volatility_adaptive_memory.parquet"
)

print()
