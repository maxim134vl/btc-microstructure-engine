import pandas as pd

# ========================================
# LOAD DATASET
# ========================================

df = pd.read_parquet("btc_15m.parquet")

df["timestamp"] = pd.to_datetime(df["timestamp"])

df = df.sort_values("timestamp")

# ========================================
# SPLITS
# ========================================

train = df[
    (df["timestamp"] >= "2020-01-01") &
    (df["timestamp"] < "2024-01-01")
].copy()

validation = df[
    (df["timestamp"] >= "2024-01-01") &
    (df["timestamp"] < "2025-01-01")
].copy()

test = df[
    (df["timestamp"] >= "2025-01-01")
].copy()

# ========================================
# SAVE
# ========================================

train.to_parquet(
    "btc_15m_train.parquet"
)

validation.to_parquet(
    "btc_15m_validation.parquet"
)

test.to_parquet(
    "btc_15m_test.parquet"
)

# ========================================
# INFO
# ========================================

print("\nTRAIN:")
print(train["timestamp"].min())
print(train["timestamp"].max())
print(len(train))

print("\nVALIDATION:")
print(validation["timestamp"].min())
print(validation["timestamp"].max())
print(len(validation))

print("\nTEST:")
print(test["timestamp"].min())
print(test["timestamp"].max())
print(len(test))

print("\nDATASETS SAVED")
