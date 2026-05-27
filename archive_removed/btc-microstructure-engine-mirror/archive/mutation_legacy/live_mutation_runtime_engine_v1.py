import pandas as pd
import numpy as np
import os

print("\nLIVE MUTATION RUNTIME ENGINE STARTED\n")

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

validation = validation.sort_values(
    "timestamp"
)

# =====================================
# LOAD BELIEF STATE
# =====================================

if os.path.exists(
    "live_recursive_beliefs.parquet"
):

    beliefs = pd.read_parquet(
        "live_recursive_beliefs.parquet"
    )

    print(
        "PREVIOUS LIVE BELIEFS LOADED\n"
    )

else:

    beliefs = pd.DataFrame(

        columns=[

            "interaction_type",

            "adaptive_weight",

            "last_updated"

        ]

    )

    print(
        "NO PREVIOUS LIVE BELIEFS\n"
    )

# =====================================
# LOAD ENGINE STATE
# =====================================

if os.path.exists(
    "live_mutation_state.parquet"
):

    state = pd.read_parquet(
        "live_mutation_state.parquet"
    )

    last_timestamp = state.iloc[-1][
        "last_processed_timestamp"
    ]

    print(
        f"LAST PROCESSED: {last_timestamp}\n"
    )

else:

    last_timestamp = None

    print(
        "NO PREVIOUS ENGINE STATE\n"
    )

# =====================================
# FILTER NEW EVENTS
# =====================================

if last_timestamp is not None:

    validation = validation[

        validation[
            "timestamp"
        ]
        >
        last_timestamp

    ]

# =====================================
# NO NEW EVENTS
# =====================================

if len(validation) == 0:

    print(
        "NO NEW VALIDATION EVENTS\n"
    )

    raise SystemExit

# =====================================
# PARAMETERS
# =====================================

reinforcement_rate = 0.10

decay_rate = 0.02

min_weight = 0.5

max_weight = 5.0

# =====================================
# PROCESS EVENTS
# =====================================

for _, row in validation.iterrows():

    timestamp = row["timestamp"]

    interaction = row[
        "interaction_type"
    ]

    outcome = row["outcome"]

    # =====================================
    # EXISTING BELIEF
    # =====================================

    existing = beliefs[

        beliefs[
            "interaction_type"
        ]
        ==
        interaction

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
    # REMOVE OLD
    # =====================================

    beliefs = beliefs[

        beliefs[
            "interaction_type"
        ]
        !=
        interaction

    ]

    # =====================================
    # APPEND NEW
    # =====================================

    new_row = pd.DataFrame([{

        "interaction_type":
            interaction,

        "adaptive_weight":
            updated_weight,

        "last_updated":
            timestamp

    }])

    beliefs = pd.concat(

        [
            beliefs,
            new_row
        ],

        ignore_index=True

    )

# =====================================
# SAVE BELIEFS
# =====================================

beliefs.to_parquet(

    "live_recursive_beliefs.parquet",

    index=False

)

# =====================================
# SAVE ENGINE STATE
# =====================================

latest_timestamp = validation[
    "timestamp"
].max()

state_df = pd.DataFrame([{

    "last_processed_timestamp":
        latest_timestamp

}])

state_df.to_parquet(

    "live_mutation_state.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("LIVE RECURSIVE BELIEFS")

print("=" * 50)

print()

print(
    beliefs
)

print()

print("LAST PROCESSED EVENT:")

print(
    latest_timestamp
)

print()

print("MEMORY SAVED:")

print(
    "live_recursive_beliefs.parquet"
)

print(
    "live_mutation_state.parquet"
)

print()
