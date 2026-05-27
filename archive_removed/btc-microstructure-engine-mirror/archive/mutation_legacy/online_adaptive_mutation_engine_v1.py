import pandas as pd
import numpy as np
import os

print("\nONLINE ADAPTIVE MUTATION ENGINE STARTED\n")

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

# =====================================
# LOAD PREVIOUS WEIGHTS
# =====================================

if os.path.exists(
    "adaptive_belief_state.parquet"
):

    previous = pd.read_parquet(
        "adaptive_belief_state.parquet"
    )

    belief_map = dict(

        zip(

            previous[
                "interaction_type"
            ],

            previous[
                "adaptive_weight"
            ]

        )

    )

    print(
        "PREVIOUS BELIEF STATE LOADED\n"
    )

else:

    belief_map = {}

    print(
        "NO PREVIOUS BELIEF STATE\n"
    )

# =====================================
# PARAMETERS
# =====================================

reinforcement_rate = 0.15

decay_rate = 0.03

min_weight = 0.5

max_weight = 5.0

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

mutation_rows = []

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
    # INITIAL WEIGHT
    # =====================================

    if interaction not in belief_map:

        belief_map[
            interaction
        ] = 1.0

    current_weight = belief_map[
        interaction
    ]

    # =====================================
    # REINFORCEMENT
    # =====================================

    reinforced_weight = (

        current_weight

        +

        (
            success_rate
            *
            reinforcement_rate
        )

    )

    # =====================================
    # DECAY
    # =====================================

    decayed_weight = (

        reinforced_weight
        *
        (
            1 - decay_rate
        )

    )

    # =====================================
    # CLAMP
    # =====================================

    final_weight = max(

        min_weight,

        min(
            max_weight,
            decayed_weight
        )

    )

    final_weight = round(
        final_weight,
        4
    )

    # =====================================
    # UPDATE MAP
    # =====================================

    belief_map[
        interaction
    ] = final_weight

    # =====================================
    # SAVE ROW
    # =====================================

    mutation_rows.append({

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
            final_weight

    })

# =====================================
# BUILD DF
# =====================================

mutation_df = pd.DataFrame(
    mutation_rows
)

# =====================================
# SAVE
# =====================================

mutation_df.to_parquet(

    "adaptive_belief_state.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("ONLINE BELIEF STATE")

print("=" * 50)

print()

print(
    mutation_df
)

print()

print("BELIEF MAP")

print(
    belief_map
)

print()

print("MEMORY SAVED:")

print(
    "adaptive_belief_state.parquet"
)

print()
