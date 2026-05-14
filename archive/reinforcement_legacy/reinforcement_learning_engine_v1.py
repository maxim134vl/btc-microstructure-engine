import pandas as pd
import numpy as np

print("\nREINFORCEMENT LEARNING ENGINE STARTED\n")

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

# =====================================
# UNIQUE INTERACTIONS
# =====================================

interaction_types = list(

    validation[
        "interaction_type"
    ].unique()

)

# =====================================
# STORAGE
# =====================================

learning_rows = []

weights = {}

# =====================================
# LOOP
# =====================================

for interaction in interaction_types:

    subset = validation[

        validation[
            "interaction_type"
        ]
        ==
        interaction

    ]

    total = len(subset)

    successful = len(

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

    if total > 0:

        success_rate = (
            successful / total
        )

    else:

        success_rate = 0

    # =====================================
    # WEIGHT
    # =====================================

    weight = round(

        1 + (
            success_rate * 2
        ),

        4

    )

    weights[
        interaction
    ] = weight

    # =====================================
    # SAVE
    # =====================================

    learning_rows.append({

        "interaction_type":
            interaction,

        "total_events":
            total,

        "successful_events":
            successful,

        "success_rate":
            round(
                success_rate,
                4
            ),

        "adaptive_weight":
            weight

    })

# =====================================
# BUILD DF
# =====================================

learning_df = pd.DataFrame(
    learning_rows
)

# =====================================
# SAVE
# =====================================

learning_df.to_parquet(

    "reinforcement_learning_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("ADAPTIVE WEIGHTS")

print("=" * 50)

print()

print(learning_df)

print()

print("WEIGHT MAP")

print(weights)

print()

print("MEMORY SAVED:")

print(
    "reinforcement_learning_memory.parquet"
)

print()
