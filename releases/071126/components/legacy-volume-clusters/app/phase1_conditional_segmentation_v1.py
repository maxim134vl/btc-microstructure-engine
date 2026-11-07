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
# FEATURES
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

df["direction_change"] = (
    df["bullish"]
    != df["bullish"].shift(1)
).astype(int)

df["rotational_conflict"] = (
    df["direction_change"]
    .rolling(10)
    .sum()
)

df["body_strength"] = (
    abs(df["body"])
    / (
        df["range"] + 1e-9
    )
)

# =========================================
# CONDITIONS
# =========================================

high_vol = (
    df["volatility"]
    > df["volatility"].quantile(0.9)
)

low_vol = (
    df["volatility"]
    < df["volatility"].quantile(0.3)
)

high_conflict = (
    df["rotational_conflict"]
    > df["rotational_conflict"].quantile(0.9)
)

low_conflict = (
    df["rotational_conflict"]
    < df["rotational_conflict"].quantile(0.3)
)

strong_body = (
    df["body_strength"]
    > df["body_strength"].quantile(0.8)
)

# =========================================
# SEGMENTS
# =========================================

segments = {

    "HIGH_VOL_HIGH_CONFLICT":
        high_vol & high_conflict,

    "LOW_VOL_LOW_CONFLICT":
        low_vol & low_conflict,

    "STRONG_BODY_HIGH_CONFLICT":
        strong_body & high_conflict,

    "STRONG_BODY_LOW_CONFLICT":
        strong_body & low_conflict

}

# =========================================
# ANALYSIS
# =========================================

results = []

for name, condition in segments.items():

    sample = df[condition]

    mean_return = (
        sample["future_return_4"]
        .mean()
    )

    median_return = (
        sample["future_return_4"]
        .median()
    )

    std_return = (
        sample["future_return_4"]
        .std()
    )

    count = len(sample)

    print("\n======================")
    print(name)
    print("======================")

    print("COUNT:")
    print(count)

    print("MEAN RETURN:")
    print(mean_return)

    print("MEDIAN RETURN:")
    print(median_return)

    print("STD:")
    print(std_return)

    results.append({

        "segment": name,
        "count": count,
        "mean_return": mean_return,
        "median_return": median_return,
        "std_return": std_return

    })

# =========================================
# SAVE
# =========================================

results_df = pd.DataFrame(results)

results_df.to_csv(
    "phase1_conditional_segmentation_results.csv",
    index=False
)

print("\nSEGMENTATION RESULTS SAVED")
