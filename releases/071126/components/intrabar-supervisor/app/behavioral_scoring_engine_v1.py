import pandas as pd
import numpy as np

print("\nBEHAVIORAL SCORING ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "market_context_memory.parquet"
)

df = df.dropna().copy()

# =====================================
# SPREAD SCORE
# relative spread expansion
# =====================================

df["spread_score"] = (

    df["spread_zscore"]

    .clip(-3, 3)

)

# =====================================
# VOLUME SCORE
# relative participation
# =====================================

df["volume_score"] = (

    df["volume_zscore"]

    .clip(-3, 3)

)

# =====================================
# DIRECTIONAL SCORE
# body efficiency inside spread
# =====================================

df["directional_score"] = (

    df["body"]

    /

    (

        df["spread"]

        +

        0.000001

    )

)

# =====================================
# LOWER REJECTION SCORE
# =====================================

df["lower_rejection_score"] = (

    df["lower_wick"]

    /

    (

        df["spread"]

        +

        0.000001

    )

)

# =====================================
# UPPER REJECTION SCORE
# =====================================

df["upper_rejection_score"] = (

    df["upper_wick"]

    /

    (

        df["spread"]

        +

        0.000001

    )

)

# =====================================
# PARTICIPATION SCORE
# =====================================

df["participation_score"] = (

    df["volume_expansion"]

)

# =====================================
# TREND PRESSURE SCORE
# =====================================

df["trend_pressure_score"] = (

    df["rolling_price_move_5"]

    /

    (

        df["rolling_spread_5"]

        +

        0.000001

    )

)

# =====================================
# EFFORT VS RESULT
# how much volume produced movement
# =====================================

df["effort_result_score"] = (

    abs(df["price_change"])

    /

    (

        df["volume_expansion"]

        +

        0.000001

    )

)

# =====================================
# CLOSE STRENGTH SCORE
# =====================================

df["close_strength_score"] = (

    df["close_position"]

)

# =====================================
# BALANCED / IMBALANCED BEHAVIOR
# =====================================

df["imbalance_score"] = (

    abs(

        df["spread_score"]

        *

        df["volume_score"]

    )

)

# =====================================
# SAVE MEMORY
# =====================================

df.to_parquet(
    "behavioral_scoring_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("BEHAVIORAL SCORING DEBUG")

print("=" * 50)

print()

debug_cols = [

    "close",

    "volume_class",

    "spread_score",

    "volume_score",

    "directional_score",

    "lower_rejection_score",

    "upper_rejection_score",

    "participation_score",

    "trend_pressure_score",

    "effort_result_score",

    "close_strength_score",

    "imbalance_score"

]

print(

    df[debug_cols]

    .tail(20)

)

print()

print("MEMORY SAVED:")

print(
    "behavioral_scoring_memory.parquet"
)

print()
