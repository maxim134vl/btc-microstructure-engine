import pandas as pd
import numpy as np

# =====================================
# LOAD RAW 5M DATA
# =====================================

df = pd.read_parquet(
    "btc_5m.parquet"
)

# =====================================
# BASIC STRUCTURE
# =====================================

df["spread"] = (
    df["high"]
    -
    df["low"]
)

df["body"] = (
    df["close"]
    -
    df["open"]
).abs()

df["upper_wick"] = (

    df["high"]

    -

    np.maximum(
        df["open"],
        df["close"]
    )

)

df["lower_wick"] = (

    np.minimum(
        df["open"],
        df["close"]
    )

    -

    df["low"]

)

# =====================================
# SAVE
# =====================================

df.to_parquet(

    "candle_structure_memory_5m.parquet"

)

# =====================================
# DONE
# =====================================

print()
print(
    "5M STRUCTURE MEMORY SAVED"
)

print(
    "candle_structure_memory_5m.parquet"
)

print()
