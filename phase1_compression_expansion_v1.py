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
# COMPRESSION
# =========================================

df["volatility_mean_20"] = (
    df["volatility"]
    .rolling(20)
    .mean()
)

compression = (

    df["volatility_mean_20"]
    < df["volatility_mean_20"].quantile(0.2)

)

# =========================================
# FUTURE INSTABILITY
# =========================================

df["future_conflict_16"] = (
    df["rotational_conflict"]
    .shift(-16)
)

df["future_volatility_16"] = (
    df["volatility"]
    .rolling(16)
    .mean()
    .shift(-16)
)

# =========================================
# EXPANSION STATES
# =========================================

compression_sample = df[
    compression
]

print("\n======================")
print("COMPRESSION SAMPLE")
print("======================")

print(len(compression_sample))

# =========================================
# FUTURE CONFLICT
# =========================================

print("\n======================")
print("FUTURE CONFLICT AFTER COMPRESSION")
print("======================")

print(
    compression_sample[
        "future_conflict_16"
    ].describe()
)

# =========================================
# FUTURE VOLATILITY
# =========================================

print("\n======================")
print("FUTURE VOLATILITY AFTER COMPRESSION")
print("======================")

print(
    compression_sample[
        "future_volatility_16"
    ].describe()
)

# =========================================
# EXPLOSIVE EXPANSION
# =========================================

high_future_conflict = (

    compression_sample[
        "future_conflict_16"
    ]

    >

    df["future_conflict_16"]
    .quantile(0.9)

)

explosive = compression_sample[
    high_future_conflict
]

print("\n======================")
print("EXPLOSIVE POST-COMPRESSION STATES")
print("======================")

print(len(explosive))

# =========================================
# FUTURE RETURNS
# =========================================

for lag in [16, 32, 64]:

    df[f"future_return_{lag}"] = (

        df["close"].shift(-lag)
        - df["close"]

    ) / df["close"]

# =========================================
# REBUILD EXPLOSIVE SAMPLE
# =========================================

explosive = df.loc[
    explosive.index
]

# =========================================
# RETURN ANALYSIS
# =========================================

for lag in [16, 32, 64]:

    print("\n======================")
    print(f"FUTURE RETURN {lag}")
    print("======================")

    print(
        explosive[
            f"future_return_{lag}"
        ].describe()
    )

# =========================================
# SAVE RESULTS
# =========================================

results = pd.DataFrame({

    "metric": [

        "compression_future_conflict_mean",
        "compression_future_volatility_mean",
        "explosive_count"

    ],

    "value": [

        compression_sample[
            "future_conflict_16"
        ].mean(),

        compression_sample[
            "future_volatility_16"
        ].mean(),

        len(explosive)

    ]

})

results.to_csv(

    "phase1_compression_expansion_results.csv",
    index=False

)

print("\nCOMPRESSION EXPANSION RESULTS SAVED")
