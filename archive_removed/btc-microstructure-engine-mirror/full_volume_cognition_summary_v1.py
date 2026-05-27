import pandas as pd

# =====================================
# LOAD DATA
# =====================================

df = pd.read_parquet(
    "historical_volume_cognition.parquet"
)

print()
print(
    "=" * 50
)

print(
    "FULL VOLUME COGNITION SUMMARY"
)

print(
    "=" * 50
)

# =====================================
# GENERAL INFO
# =====================================

print()
print(
    "TOTAL ROWS:",
    len(df)
)

# =====================================
# VOLUME CLASS
# =====================================

print()
print(
    "=" * 50
)

print(
    "VOLUME CLASS DISTRIBUTION"
)

print()

print(
    df["volume_class"]
    .value_counts(normalize=True)
    * 100
)

# =====================================
# PARTICIPATION
# =====================================

print()
print(
    "=" * 50
)

print(
    "PARTICIPATION DISTRIBUTION"
)

print()

print(
    df["participation_state"]
    .value_counts(normalize=True)
    * 100
)

# =====================================
# EFFORT RESULT
# =====================================

print()
print(
    "=" * 50
)

print(
    "EFFORT RESULT DISTRIBUTION"
)

print()

print(
    df["effort_result_state"]
    .value_counts(normalize=True)
    * 100
)

# =====================================
# UNFINISHED AUCTIONS
# =====================================

print()
print(
    "=" * 50
)

print(
    "UNFINISHED AUCTION RATE"
)

print()

print(
    df["unfinished_auction"]
    .value_counts(normalize=True)
    * 100
)

# =====================================
# CONTINUATION QUALITY
# =====================================

print()
print(
    "=" * 50
)

print(
    "CONTINUATION QUALITY"
)

print()

print(
    df["continuation_quality"]
    .value_counts(normalize=True)
    * 100
)

# =====================================
# DELTA EFFICIENCY
# =====================================

print()
print(
    "=" * 50
)

print(
    "DELTA EFFICIENCY STATS"
)

print()

print(
    df["delta_efficiency"]
    .describe()
)

print()
