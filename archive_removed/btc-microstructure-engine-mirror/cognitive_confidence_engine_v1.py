import pandas as pd
import numpy as np
import os

print("\nCOGNITIVE CONFIDENCE ENGINE STARTED\n")

# =====================================
# LOAD BELIEFS
# =====================================

beliefs = pd.read_parquet(
    "live_recursive_beliefs.parquet"
)

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

confidence_rows = []

# =====================================
# LOOP BELIEFS
# =====================================

for _, row in beliefs.iterrows():

    interaction = row[
        "interaction_type"
    ]

    weight = float(
        row["adaptive_weight"]
    )

    # =====================================
    # VALIDATION HISTORY
    # =====================================

    subset = validation[

        validation[
            "interaction_type"
        ]
        ==
        interaction

    ]

    total_events = len(subset)

    successful_events = len(

        subset[
            subset[
                "outcome"
            ]
            !=
            "neutral"
        ]

    )

    # =====================================
    # SUCCESS RATE
    # =====================================

    if total_events > 0:

        success_rate = (

            successful_events
            /
            total_events

        )

    else:

        success_rate = 0

    # =====================================
    # SAMPLE CONFIDENCE
    # =====================================

    sample_confidence = min(

        1.0,

        total_events / 100

    )

    # =====================================
    # STABILITY
    # =====================================

    stability = (

        weight
        *
        success_rate
        *
        sample_confidence

    )

    stability = round(
        stability,
        4
    )

    # =====================================
    # CONFIDENCE CLASS
    # =====================================

    confidence = "low_confidence"

    if stability > 0.5:

        confidence = (
            "moderate_confidence"
        )

    if stability > 1.0:

        confidence = (
            "high_confidence"
        )

    # =====================================
    # SAVE
    # =====================================

    confidence_rows.append({

        "interaction_type":
            interaction,

        "adaptive_weight":
            weight,

        "total_events":
            total_events,

        "successful_events":
            successful_events,

        "success_rate":
            round(
                success_rate,
                4
            ),

        "sample_confidence":
            round(
                sample_confidence,
                4
            ),

        "stability_score":
            stability,

        "confidence":
            confidence

    })

# =====================================
# BUILD DF
# =====================================

confidence_df = pd.DataFrame(
    confidence_rows
)

# =====================================
# SAVE
# =====================================

confidence_df.to_parquet(

    "cognitive_confidence_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("COGNITIVE CONFIDENCE")

print("=" * 50)

print()

print(
    confidence_df
)

print()

print("=" * 50)

print("CONFIDENCE DISTRIBUTION")

print("=" * 50)

print()

print(

    confidence_df[
        "confidence"
    ].value_counts()

)

print()

print("MEMORY SAVED:")

print(
    "cognitive_confidence_memory.parquet"
)

print()
