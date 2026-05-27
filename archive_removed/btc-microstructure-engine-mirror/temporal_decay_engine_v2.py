import pandas as pd
import numpy as np

print("\nTEMPORAL DECAY ENGINE V2 STARTED\n")

# =====================================
# LOAD BELIEFS
# =====================================

beliefs = pd.read_parquet(
    "live_recursive_beliefs.parquet"
)

# =====================================
# CURRENT TIME
# =====================================

current_time = pd.Timestamp.now()

# =====================================
# PARAMETERS
# =====================================

daily_decay_rate = 0.03

min_weight = 0.5

# =====================================
# STORAGE
# =====================================

decay_rows = []

updated_weights = []

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
    # LAST UPDATED
    # =====================================

    last_updated = pd.Timestamp(

        row["last_updated"]

    )

    # remove timezone if exists

    if last_updated.tzinfo is not None:

        last_updated = (

            last_updated
            .tz_localize(None)

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

    updated_weights.append(
        decayed_weight
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
# UPDATE BELIEFS
# =====================================

beliefs[
    "adaptive_weight"
] = updated_weights

beliefs.to_parquet(

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
