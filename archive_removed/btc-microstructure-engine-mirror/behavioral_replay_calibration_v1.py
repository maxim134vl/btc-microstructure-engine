import pandas as pd

print()
print("BEHAVIORAL REPLAY CALIBRATION")
print()

# =====================================
# LOAD DATA
# =====================================

sequences = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

# =====================================
# PREPARE
# =====================================

results = []

# =====================================
# REPLAY
# =====================================

for i in range(
    len(sequences) - 5
):

    current = (
        sequences.iloc[i]
    )

    future = (
        sequences.iloc[i + 5]
    )

    sequence = (
        current[
            "sequence"
        ]
    )

    persistence = (
        current[
            "persistence"
        ]
    )

    future_behavior = (
        future[
            "sequence"
        ]
    )

    outcome = (
        "NEUTRAL"
    )

    # ---------------------------------

    if (

        sequence == (
            "EXHAUSTION_SEQUENCE"
        )

        and

        future_behavior != (
            "EXHAUSTION_SEQUENCE"
        )

    ):

        outcome = (
            "EXHAUSTION_RESOLVED"
        )

    # ---------------------------------

    if (

        sequence == (
            "FAILED_CONTINUATION_SEQUENCE"
        )

        and

        future_behavior == (
            "EXHAUSTION_SEQUENCE"
        )

    ):

        outcome = (
            "CONTINUATION_COLLAPSED"
        )

    # ---------------------------------

    if (

        sequence == (
            "ABSORPTION_SEQUENCE"
        )

        and

        future_behavior == (
            "ABSORPTION_SEQUENCE"
        )

    ):

        outcome = (
            "PERSISTENT_ABSORPTION"
        )

    # =================================
    # SAVE
    # =================================

    results.append({

        "sequence":
            sequence,

        "persistence":
            persistence,

        "future_behavior":
            future_behavior,

        "outcome":
            outcome

    })

# =====================================
# DATAFRAME
# =====================================

df = pd.DataFrame(
    results
)

if len(df) == 0:

    print(
        "NOT ENOUGH REPLAY DATA"
    )

    print()

    exit()

# =====================================
# SUMMARY
# =====================================

summary = (

    df.groupby(
        [
            "sequence",
            "outcome"
        ]
    )

    .size()

    .reset_index(
        name="count"
    )

)

# =====================================
# OUTPUT
# =====================================

print(summary)

print()

print(
    "TOTAL REPLAY EVENTS:"
)

print(
    len(df)
)

print()
