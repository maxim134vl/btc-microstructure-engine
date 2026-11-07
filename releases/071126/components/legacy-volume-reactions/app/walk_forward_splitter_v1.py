import pandas as pd

# ========================================
# LOAD DATA
# ========================================

df = pd.read_parquet("btc_15m.parquet")

df["timestamp"] = pd.to_datetime(df["timestamp"])

df = df.sort_values("timestamp")

# ========================================
# WALK-FORWARD WINDOWS
# ========================================

windows = [

    {
        "name": "wf_window_1",
        "train_start": "2020-01-01",
        "train_end": "2022-12-31",
        "validation_start": "2023-01-01",
        "validation_end": "2023-12-31"
    },

    {
        "name": "wf_window_2",
        "train_start": "2021-01-01",
        "train_end": "2023-12-31",
        "validation_start": "2024-01-01",
        "validation_end": "2024-12-31"
    },

    {
        "name": "wf_window_3",
        "train_start": "2022-01-01",
        "train_end": "2024-12-31",
        "validation_start": "2025-01-01",
        "validation_end": "2025-12-31"
    }

]

# ========================================
# GENERATE SPLITS
# ========================================

for window in windows:

    train = df[
        (df["timestamp"] >= window["train_start"]) &
        (df["timestamp"] <= window["train_end"])
    ].copy()

    validation = df[
        (df["timestamp"] >= window["validation_start"]) &
        (df["timestamp"] <= window["validation_end"])
    ].copy()

    # SAVE TRAIN

    train.to_parquet(
        f"{window['name']}_train.parquet"
    )

    # SAVE VALIDATION

    validation.to_parquet(
        f"{window['name']}_validation.parquet"
    )

    # INFO

    print("\n====================")
    print(window["name"])

    print("\nTRAIN")

    print(train["timestamp"].min())
    print(train["timestamp"].max())
    print(len(train))

    print("\nVALIDATION")

    print(validation["timestamp"].min())
    print(validation["timestamp"].max())
    print(len(validation))

print("\nWALK-FORWARD DATASETS SAVED")
