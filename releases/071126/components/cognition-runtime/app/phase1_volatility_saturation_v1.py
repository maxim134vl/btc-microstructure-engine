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

# =========================================
# FUTURE RETURNS
# =========================================

lags = [16, 32, 64]

for lag in lags:

    df[f"future_return_{lag}"] = (

        df["close"].shift(-lag)
        - df["close"]

    ) / df["close"]

# =========================================
# EXTREME VOLATILITY
# =========================================

extreme_volatility = (

    df["volatility"]
    > df["volatility"].quantile(0.99)

)

sample = df[
    extreme_volatility
]

print("\n======================")
print("EXTREME VOLATILITY SAMPLE")
print("======================")

print(len(sample))

# =========================================
# FUTURE RETURNS
# =========================================

results = []

for lag in lags:

    col = f"future_return_{lag}"

    print("\n======================")
    print(f"FUTURE RETURN {lag}")
    print("======================")

    stats = sample[col].describe()

    print(stats)

    results.append({

        "lag": lag,
        "mean_return": sample[col].mean(),
        "median_return": sample[col].median(),
        "std_return": sample[col].std()

    })

# =========================================
# RETENTION FAILURE
# =========================================

df["retention"] = (

    abs(
        df["close"].shift(-16)
        - df["close"]
    )

    /

    (
        abs(df["range"]) + 1e-9
    )

)

# =========================================
# REBUILD SAMPLE
# =========================================

sample = df.loc[
    sample.index
]

sample_retention = sample[
    "retention"
]

print("\n======================")
print("RETENTION AFTER EXTREME VOLATILITY")
print("======================")

print(
    sample_retention.describe()
)

print("\n======================")
print("RETENTION AFTER EXTREME VOLATILITY")
print("======================")

print(
    sample_retention.describe()
)

# =========================================
# SAVE RESULTS
# =========================================

results_df = pd.DataFrame(results)

results_df.to_csv(

    "phase1_volatility_saturation_results.csv",
    index=False

)

print("\nVOLATILITY SATURATION RESULTS SAVED")
