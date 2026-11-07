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
# PROGRESSION EFFICIENCY
# =========================================

df["future_return_4"] = (
    df["close"].shift(-4)
    - df["close"]
) / df["close"]

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
# LAGGED RETURNS
# =========================================

lags = [8, 16, 32, 64]

for lag in lags:

    df[f"future_return_{lag}"] = (

        df["close"].shift(-lag)
        - df["close"]

    ) / df["close"]

# =========================================
# COMBINED INSTABILITY
# =========================================

combined_instability = (

    (
        df["conflict_acceleration"]
        > df["conflict_acceleration"].quantile(0.9)
    )

    &

    (
        df["efficiency_decay"]
        < df["efficiency_decay"].quantile(0.1)
    )

)

sample = df[
    combined_instability
]

print("\n======================")
print("COMBINED INSTABILITY SAMPLE")
print("======================")

print(len(sample))

# =========================================
# LAG ANALYSIS
# =========================================

results = []

for lag in lags:

    col = f"future_return_{lag}"

    mean_return = (
        sample[col].mean()
    )

    median_return = (
        sample[col].median()
    )

    std_return = (
        sample[col].std()
    )

    print("\n======================")
    print(f"LAG {lag}")
    print("======================")

    print("MEAN:")
    print(mean_return)

    print("MEDIAN:")
    print(median_return)

    print("STD:")
    print(std_return)

    results.append({

        "lag": lag,
        "mean_return": mean_return,
        "median_return": median_return,
        "std_return": std_return

    })

# =========================================
# SAVE RESULTS
# =========================================

results_df = pd.DataFrame(results)

results_df.to_csv(

    "phase1_lagged_instability_results.csv",
    index=False

)

print("\nLAGGED INSTABILITY RESULTS SAVED")
