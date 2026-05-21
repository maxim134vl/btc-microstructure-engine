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
# DIRECTIONAL CONTROL
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
# RETURNS
# =========================================

for lag in [16, 32, 64]:

    df[f"future_return_{lag}"] = (

        df["close"].shift(-lag)
        - df["close"]

    ) / df["close"]

# =========================================
# PROGRESSION EFFICIENCY
# =========================================

df["progression_efficiency"] = (

    abs(df["future_return_16"])

    /

    (
        df["volatility"] + 1e-9
    )

)

# =========================================
# EXTREME EXPANSION
# =========================================

extreme_expansion = (

    df["volatility"]
    > df["volatility"].quantile(0.99)

)

# =========================================
# TERMINATION CANDIDATES
# =========================================

termination = (

    extreme_expansion

    &

    (
        df["progression_efficiency"]
        < df["progression_efficiency"].quantile(0.2)
    )

    &

    (
        df["rotational_conflict"]
        > df["rotational_conflict"].quantile(0.8)
    )

)

sample = df[
    termination
]

print("\n======================")
print("TERMINATION SAMPLE")
print("======================")

print(len(sample))

# =========================================
# RETURN ANALYSIS
# =========================================

results = []

for lag in [16, 32, 64]:

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
# RETENTION
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

sample = df.loc[
    sample.index
]

print("\n======================")
print("RETENTION")
print("======================")

print(
    sample["retention"].describe()
)

# =========================================
# SAVE
# =========================================

results_df = pd.DataFrame(results)

results_df.to_csv(

    "phase1_expansion_termination_results.csv",
    index=False

)

print("\nEXPANSION TERMINATION RESULTS SAVED")
