import pandas as pd
import numpy as np

print("\nTEST RECOGNITION ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

zones = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

tests = []

# =====================================
# LOOP
# =====================================

for i in range(1, len(candles)):

    current = candles.iloc[i]

    previous_zone = zones.iloc[i - 1]

    zone_low = previous_zone["zone_low"]

    zone_high = previous_zone["zone_high"]

    low = current["low"]

    high = current["high"]

    close = current["close"]

    volume = current["volume"]

    spread = current["spread"]

    # =====================================
    # TEST DETECTION
    # =====================================

    revisit = (

        high >= zone_low

        and

        low <= zone_high

    )

    successful_test = False

    failed_test = False

    test_type = "none"

    # =====================================
    # SUCCESSFUL TEST
    # =====================================

    if revisit:

        # low volume revisit

        if (

            volume
            <
            candles["volume"]
            .rolling(10)
            .mean()
            .iloc[i]

        ):

            # close rejected away

            if close > zone_high:

                successful_test = True

                test_type = (
                    "successful_defended_test"
                )

            elif close < zone_low:

                failed_test = True

                test_type = (
                    "failed_defended_test"
                )

    # =====================================
    # SAVE
    # =====================================

    tests.append({

        "timestamp": current["timestamp"],

        "revisit": revisit,

        "successful_test": successful_test,

        "failed_test": failed_test,

        "test_type": test_type,

        "tested_zone_low": zone_low,

        "tested_zone_high": zone_high

    })

# =====================================
# BUILD DF
# =====================================

tests_df = pd.DataFrame(
    tests
)

# =====================================
# SAVE
# =====================================

tests_df.to_parquet(
    "test_recognition_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("TEST RECOGNITION DEBUG")

print("=" * 50)

print()

if len(tests_df) == 0:

    print("NO TEST EVENTS YET")

else:

    print(
        tests_df["test_type"]
        .value_counts()
    )

    print()

    print(
        tests_df.tail(20)
    )

print()

print("MEMORY SAVED:")

print(
    "test_recognition_memory.parquet"
)

print()
