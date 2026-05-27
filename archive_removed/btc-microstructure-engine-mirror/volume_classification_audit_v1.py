import pandas as pd

# =====================================
# LOAD DATA
# =====================================

volume = pd.read_parquet(
    "historical_volume_cognition.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# MERGE
# =====================================

df = candles.merge(

    volume,

    on="timestamp",

    how="left"

)

# =====================================
# FILTER IMPORTANT STATES
# =====================================

important = df[

    df["volume_class"].isin(

        [
            "climax",
            "stopping"
        ]

    )

].copy()

# =====================================
# SELECT COLUMNS
# =====================================

important = important[

    [

        "timestamp",

        "open",
        "high",
        "low",
        "close",

        "volume",

        "delta",

        "spread",

        "body",

        "upper_wick",
        "lower_wick",

        "volume_class"

    ]

]

# =====================================
# SORT
# =====================================

important = important.sort_values(
    "timestamp"
)

# =====================================
# ROUNDING
# =====================================

numeric_cols = [

    "open",
    "high",
    "low",
    "close",

    "volume",

    "delta",

    "spread",

    "body",

    "upper_wick",
    "lower_wick"

]

important[numeric_cols] = important[
    numeric_cols
].round(2)

# =====================================
# SAVE CSV
# =====================================

important.to_csv(

    "volume_classification_audit.csv",

    index=False

)

# =====================================
# SUMMARY
# =====================================

print()
print(
    "TOTAL IMPORTANT STATES:",
    len(important)
)

print()

print(
    important[
        "volume_class"
    ].value_counts()
)

print()

print(
    "AUDIT SAVED:"
)

print(
    "volume_classification_audit.csv"
)

print()
