import pandas as pd
import numpy as np

# =========================================
# LOAD DATA
# =========================================

df = pd.read_parquet(
    "btc_15m_train.parquet"
)

print("\nDATA LOADED")

# =========================================
# BASIC FEATURES
# =========================================

df["future_return_4"] = (
    df["close"].shift(-4)
    - df["close"]
) / df["close"]

df["body"] = (
    df["close"] - df["open"]
)

df["range"] = (
    df["high"] - df["low"]
)

df["volatility"] = (
    df["range"]
    / df["close"]
)

df["bullish"] = (
    df["body"] > 0
).astype(int)

# =========================================
# ROTATIONAL CONFLICT
# =========================================

df["direction_change"] = (
    df["bullish"]
    != df["bullish"].shift(1)
).astype(int)

df["rotational_conflict"] = (
    df["direction_change"]
    .rolling(10)
    .sum()
)

# =========================================
# PROGRESSION EFFICIENCY
# =========================================

df["progression_efficiency"] = (
    abs(df["future_return_4"])
    / (
        df["volatility"] + 1e-9
    )
)

# =========================================
# TEMPORAL INSTABILITY
# =========================================

df["conflict_acceleration"] = (
    df["rotational_conflict"]
    - df["rotational_conflict"].shift(5)
)

df["efficiency_decay"] = (
    df["progression_efficiency"]
    - df["progression_efficiency"].shift(5)
)

# =========================================
# HIGH INSTABILITY STATES
# =========================================

high_acceleration = df[
    df["conflict_acceleration"]
    > df["conflict_acceleration"].quantile(0.9)
]

high_decay = df[
    df["efficiency_decay"]
    < df["efficiency_decay"].quantile(0.1)
]

# =========================================
# ANALYSIS
# =========================================

print("\n======================")
print("HIGH CONFLICT ACCELERATION")
print("======================")

print(
    high_acceleration[
        "future_return_4"
    ].describe()
)

print("\n======================")
print("HIGH EFFICIENCY DECAY")
print("======================")

print(
    high_decay[
        "future_return_4"
    ].describe()
)

# =========================================
# COMBINED INSTABILITY
# =========================================

combined_instability = df[

    (
        df["conflict_acceleration"]
        > df["conflict_acceleration"].quantile(0.9)
    )

    &

    (
        df["efficiency_decay"]
        < df["efficiency_decay"].quantile(0.1)
    )

]

print("\n======================")
print("COMBINED INSTABILITY")
print("======================")

print(
    combined_instability[
        "future_return_4"
    ].describe()
)

# =========================================
# SAVE RESULTS
# =========================================

results = pd.DataFrame({

    "metric": [

        "high_conflict_acceleration_return",
        "high_efficiency_decay_return",
        "combined_instability_return"

    ],

    "value": [

        high_acceleration[
            "future_return_4"
        ].mean(),

        high_decay[
            "future_return_4"
        ].mean(),

        combined_instability[
            "future_return_4"
        ].mean()

    ]

})

results.to_csv(

    "phase1_temporal_instability_results.csv",
    index=False

)

print("\nTEMPORAL INSTABILITY RESULTS SAVED")
