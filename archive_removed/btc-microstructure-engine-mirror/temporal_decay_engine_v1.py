import pandas as pd
import numpy as np
from datetime import datetime

print("\nTEMPORAL DECAY ENGINE STARTED\n")

# =====================================
# LOAD BELIEFS
# =====================================

beliefs = pd.read_parquet(
    "live_recursive_beliefs.parquet"
)

# =====================================
# CURRENT TIME
# =====================================

current_time = pd.Timestamp.utcnow()

# =====================================
# PARAMETERS
# =====================================

daily_decay_rate = 0.03

min_weight = 0.5

# =====================================
# STORAGE
# =====================================

decay_rows = []

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

    last_updated = pd.Timestamp(

        row["last_updated"]

    )

    # =====================================
    # AGE
    # =====================================

    age_days = (

        current_time
        -
        last_updated

    ).total_seconds() / 86400

    age_days = max(
        age_days,
        0
    )

    # =====================================
    # DECAY
    # =====================================

    decay_multiplier = (

        1
        -
        (
            daily_decay_rate
            *
            age_days
        )

    )

    decay_multiplier = max(
        decay_multiplier,
        0
    )

    decayed_weight = (

        weight
        *
        decay_multiplier

    )

    decayed_weight = max(

        min_weight,

        decayed_weight

    )

    decayed_weight = round(
        decayed_weight,
        4
    )

    # =====================================
    # SAVE
    # =====================================

    decay_rows.append({

        "interaction_type":
            interaction,

        "previous_weight":
            weight,

        "age_days":
            round(
                age_days,
                4
            ),

        "decayed_weight":
            decayed_weight

    })

# =====================================
# BUILD DF
# =====================================

decay_df = pd.DataFrame(
    decay_rows
)

# =====================================
# SAVE UPDATED BELIEFS
# =====================================

updated_beliefs = beliefs.copy()

updated_beliefs[
    "adaptive_weight"
] = decay_df[
    "decayed_weight"
]

updated_beliefs.to_parquet(

    "live_recursive_beliefs.parquet",

    index=False

)

# =====================================
# SAVE MEMORY
# =====================================

decay_df.to_parquet(

    "temporal_decay_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("TEMPORAL DECAY")

print("=" * 50)

print()

print(
    decay_df
)

print()

print("UPDATED BELIEFS SAVED")

print(
    "live_recursive_beliefs.parquet"
)

print()

print("DECAY MEMORY SAVED")

print(
    "temporal_decay_memory.parquet"
)

print()
