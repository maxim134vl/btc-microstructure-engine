import pandas as pd
import numpy as np

# =========================================
# LOAD TRAIN DATA
# =========================================

df = pd.read_parquet(
    "btc_15m_train.parquet"
)

print("\nTRAIN DATA LOADED")

print(df.columns)

print(df.head())

# =========================================
# BASIC RETURNS
# =========================================

df["future_return_4"] = (
    df["close"]
    .shift(-4)
    - df["close"]
) / df["close"]

# =========================================
# CANDLE STRUCTURE
# =========================================

df["body"] = (
    df["close"] - df["open"]
)

df["range"] = (
    df["high"] - df["low"]
)

df["body_ratio"] = (
    abs(df["body"])
    / (
        df["range"] + 1e-9
    )
)

# =========================================
# DIRECTIONAL STATE
# =========================================

df["bullish"] = (
    df["body"] > 0
).astype(int)

# =========================================
# VOLATILITY
# =========================================

df["volatility"] = (
    df["range"]
    / df["close"]
)

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
# CONTINUATION EFFICIENCY
# =========================================

df["continuation_efficiency"] = (
    abs(df["future_return_4"])
    / (
        df["volatility"] + 1e-9
    )
)

# =========================================
# ANALYSIS
# =========================================

print("\n======================")
print("CONTINUATION EFFICIENCY")
print("======================")

print(
    df["continuation_efficiency"]
    .describe()
)

print("\n======================")
print("ROTATIONAL CONFLICT")
print("======================")

print(
    df["rotational_conflict"]
    .describe()
)

print("\n======================")
print("VOLATILITY")
print("======================")

print(
    df["volatility"]
    .describe()
)

# =========================================
# HIGH VOLATILITY ANALYSIS
# =========================================

high_vol = df[
    df["volatility"]
    > df["volatility"].quantile(0.9)
]

print("\n======================")
print("HIGH VOLATILITY FUTURE RETURNS")
print("======================")

print(
    high_vol["future_return_4"]
    .describe()
)

# =========================================
# HIGH ROTATIONAL CONFLICT
# =========================================

high_conflict = df[
    df["rotational_conflict"]
    > df["rotational_conflict"].quantile(0.9)
]

print("\n======================")
print("HIGH ROTATIONAL CONFLICT RETURNS")
print("======================")

print(
    high_conflict["future_return_4"]
    .describe()
)

# =========================================
# SAVE RESULTS
# =========================================

results = pd.DataFrame({

    "metric": [

        "mean_continuation_efficiency",
        "mean_rotational_conflict",
        "mean_volatility",
        "high_volatility_return",
        "high_conflict_return"

    ],

    "value": [

        df["continuation_efficiency"].mean(),
        df["rotational_conflict"].mean(),
        df["volatility"].mean(),
        high_vol["future_return_4"].mean(),
        high_conflict["future_return_4"].mean()

    ]

})

results.to_csv(
    "phase1_rebacktest_results.csv",
    index=False
)

print("\nRESULTS SAVED")
