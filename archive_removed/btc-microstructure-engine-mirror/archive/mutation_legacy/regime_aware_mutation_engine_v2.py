import pandas as pd
import numpy as np
import os

print("\nREGIME AWARE MUTATION ENGINE V2 STARTED\n")

# =====================================
# LOAD FLOW
# =====================================

flow = pd.read_parquet(
    "live_volume_flow_memory.parquet"
)

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

# =====================================
# LOAD PREVIOUS STATE
# =====================================

if os.path.exists(
    "regime_adaptive_beliefs.parquet"
):

    previous = pd.read_parquet(
        "regime_adaptive_beliefs.parquet"
    )

    print(
        "PREVIOUS REGIME BELIEFS LOADED\n"
    )

else:

    previous = pd.DataFrame(

        columns=[

            "timestamp",

            "interaction_type",

            "regime",

            "outcome",

            "adaptive_weight"

        ]

    )

    print(
        "NO PREVIOUS REGIME BELIEFS\n"
    )

# =====================================
# REMOVE DUPLICATES
# =====================================

flow = flow.drop_duplicates(

    subset=["timestamp"],

    keep="last"

)

flow_map = flow.set_index(
    "timestamp"
)

# =====================================
# PARAMETERS
# =====================================

reinforcement_rate = 0.12

decay_rate = 0.025

min_weight = 0.5

max_weight = 5.0

# =====================================
# STORAGE
# =====================================

belief_rows = []

# =====================================
# LOOP VALIDATION
# =====================================

for _, row in validation.iterrows():

    timestamp = row["timestamp"]

    interaction = str(

        row["interaction_type"]

    )

    outcome = str(
        row["outcome"]
    )

    # =====================================
    # TIMESTAMP EXISTS
    # =====================================

    if timestamp not in flow_map.index:

        continue

    flow_state = str(

        flow_map.loc[
            timestamp
        ]["flow_state"]

    )

    # =====================================
    # REGIME
    # =====================================

    regime = "neutral_regime"

    if flow_state == "compression":

        regime = (
            "compression_regime"
        )

    elif flow_state == "aggressive_expansion":

        regime = (
            "expansion_regime"
        )

    elif flow_state == "passive_pullback":

        regime = (
            "rotational_regime"
        )

    # =====================================
    # PREVIOUS BELIEF
    # =====================================

    existing = previous[

        (

            previous[
                "interaction_type"
            ]
            ==
            interaction

        )

        &

        (

            previous[
                "regime"
            ]
            ==
            regime

        )

    ]

    if len(existing) > 0:

        current_weight = float(

            existing.iloc[-1][
                "adaptive_weight"
            ]

        )

    else:

        current_weight = 1.0

    # =====================================
    # SUCCESS
    # =====================================

    success = (

        outcome
        !=
        "neutral"

    )

    # =====================================
    # UPDATE
    # =====================================

    if success:

        updated_weight = (

            current_weight
            +
            reinforcement_rate

        )

    else:

        updated_weight = (

            current_weight

            *
            (
                1 - decay_rate
            )

        )

    # =====================================
    # CLAMP
    # =====================================

    updated_weight = max(

        min_weight,

        min(
            max_weight,
            updated_weight
        )

    )

    updated_weight = round(
        updated_weight,
        4
    )

    # =====================================
    # SAVE ROW
    # =====================================

    belief_rows.append({

        "timestamp":
            timestamp,

        "interaction_type":
            interaction,

        "regime":
            regime,

        "outcome":
            outcome,

        "adaptive_weight":
            updated_weight

    })

# =====================================
# BUILD DF
# =====================================

belief_df = pd.DataFrame(
    belief_rows
)

# =====================================
# SAVE
# =====================================

belief_df.to_parquet(

    "regime_adaptive_beliefs.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("REGIME DISTRIBUTION")

print("=" * 50)

print()

print(

    belief_df[
        "regime"
    ].value_counts()

)

print()

print("=" * 50)

print("LAST BELIEF STATES")

print("=" * 50)

print()

print(
    belief_df.tail(40)
)

print()

print("MEMORY SAVED:")

print(
    "regime_adaptive_beliefs.parquet"
)

print()
