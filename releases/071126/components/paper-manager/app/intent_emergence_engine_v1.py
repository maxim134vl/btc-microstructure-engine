import pandas as pd
import numpy as np

print("\nINTENT EMERGENCE ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

chains = pd.read_parquet(
    "event_chains_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

intent_rows = []

# =====================================
# LOOP
# =====================================

for _, row in chains.iterrows():

    chain_id = row["chain_id"]

    chain_type = row["chain_type"]

    strength = row["strength"]

    strength = row["strength"]

    events = list(
        row["events"]
    )
    # =====================================
    # COUNTS
    # =====================================

    successful_tests = events.count(
        "successful_test"
    )

    failed_tests = events.count(
        "failed_test"
    )

    absorptions = events.count(
        "absorption"
    )

    distributions = events.count(
        "distribution"
    )

    # =====================================
    # DEFAULT
    # =====================================

    market_intent = "undefined"

    confidence = 0

    # =====================================
    # ACCUMULATION
    # =====================================

    if (

        chain_type
        ==
        "defended_accumulation"

        and

        successful_tests >= 2

        and

        absorptions >= 1

    ):

        market_intent = (
            "accumulation_intent"
        )

        confidence = (

            successful_tests
            +
            absorptions
            +
            strength

        ) / 10

    # =====================================
    # DISTRIBUTION
    # =====================================

    elif (

        chain_type
        ==
        "defended_distribution"

        and

        distributions >= 1

    ):

        market_intent = (
            "distribution_intent"
        )

        confidence = (

            distributions
            +
            successful_tests
            +
            strength

        ) / 10

    # =====================================
    # BREAKOUT PRESSURE
    # =====================================

    elif (

        chain_type
        ==
        "weakening_structure"

        and

        failed_tests >= 2

    ):

        market_intent = (
            "breakout_pressure"
        )

        confidence = (

            failed_tests
            +
            strength

        ) / 10

    # =====================================
    # EXHAUSTION
    # =====================================

    elif (

        successful_tests >= 3

        and

        failed_tests >= 3

    ):

        market_intent = (
            "exhaustion_transition"
        )

        confidence = (

            successful_tests
            +
            failed_tests

        ) / 10

    # =====================================
    # SAVE
    # =====================================

    intent_rows.append({

        "chain_id": chain_id,

        "chain_type": chain_type,

        "strength": strength,

        "market_intent":
            market_intent,

        "confidence":
            round(confidence, 3),

        "successful_tests":
            successful_tests,

        "failed_tests":
            failed_tests,

        "absorptions":
            absorptions,

        "distributions":
            distributions

    })

# =====================================
# BUILD DF
# =====================================

intent_df = pd.DataFrame(
    intent_rows
)

# =====================================
# SAVE
# =====================================

intent_df.to_parquet(
    "intent_emergence_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("INTENT DEBUG")

print("=" * 50)

print()

print(
    intent_df[
        [

            "chain_id",

            "market_intent",

            "confidence",

            "strength"

        ]

    ]
    .tail(40)

)

print()

print("INTENT DISTRIBUTION:")

print(
    intent_df[
        "market_intent"
    ].value_counts()
)

print()

print("MEMORY SAVED:")

print(
    "intent_emergence_memory.parquet"
)

print()
