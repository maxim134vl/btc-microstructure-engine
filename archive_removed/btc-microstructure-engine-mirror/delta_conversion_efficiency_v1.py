import pandas as pd
import numpy as np

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# POSITIVE DELTA
# =====================================

positive = candles[
    candles["delta"] > 0
].copy()

# =====================================
# NEGATIVE DELTA
# =====================================

negative = candles[
    candles["delta"] < 0
].copy()

# =====================================
# EFFICIENCY
# =====================================

positive["efficiency"] = np.where(

    positive["delta"].abs() > 0,

    positive["body"].abs()

    /

    positive["delta"].abs(),

    0

)

negative["efficiency"] = np.where(

    negative["delta"].abs() > 0,

    negative["body"].abs()

    /

    negative["delta"].abs(),

    0

)

# =====================================
# RESULTS
# =====================================

print()
print("=" * 40)
print("POSITIVE DELTA")
print("=" * 40)

print()

print(
    "AVG EFFICIENCY:",
    round(
        positive[
            "efficiency"
        ].mean(),
        4
    )
)

print()

print("=" * 40)
print("NEGATIVE DELTA")
print("=" * 40)

print()

print(
    "AVG EFFICIENCY:",
    round(
        negative[
            "efficiency"
        ].mean(),
        4
    )
)

print()
