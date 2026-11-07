import pandas as pd
import numpy as np

print("\nDEFENDED LIQUIDITY ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

zones = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

tests = pd.read_parquet(
    "test_recognition_memory.parquet"
)

# =====================================
# EMPTY CHECK
# =====================================

if len(tests) == 0:

    print("NO TEST DATA AVAILABLE")

    exit()

# =====================================
# STORAGE
# =====================================

liquidity_memory = []

# =====================================
# LOOP
# =====================================

for i in range(len(tests)):

    test = tests.iloc[i]

    persistence_score = 0

    defense_strength = 0

    defended = False

    broken = False

    # =====================================
    # SUCCESSFUL TEST
    # =====================================

    if test["successful_test"]:

        persistence_score += 1

        defense_strength += 1

        defended = True

    # =====================================
    # FAILED TEST
    # =====================================

    if test["failed_test"]:

        persistence_score -= 1

        defense_strength -= 1

        broken = True

    # =====================================
    # SAVE
    # =====================================

    liquidity_memory.append({

        "timestamp": test["timestamp"],

        "zone_low": test[
            "tested_zone_low"
        ],

        "zone_high": test[
            "tested_zone_high"
        ],

        "defended": defended,

        "broken": broken,

        "persistence_score":
            persistence_score,

        "defense_strength":
            defense_strength

    })

# =====================================
# BUILD DF
# =====================================

liq_df = pd.DataFrame(
    liquidity_memory
)

# =====================================
# SAVE
# =====================================

liq_df.to_parquet(
    "defended_liquidity_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("DEFENDED LIQUIDITY DEBUG")

print("=" * 50)

print()

print(
    liq_df.tail(20)
)

print()

print("MEMORY SAVED:")

print(
    "defended_liquidity_memory.parquet"
)

print()
