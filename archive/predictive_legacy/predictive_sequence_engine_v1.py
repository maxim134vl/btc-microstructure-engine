import pandas as pd
import numpy as np

print("\nPREDICTIVE SEQUENCE ENGINE STARTED\n")

# =====================================
# LOAD FRACTAL MEMORY
# =====================================

memory = pd.read_parquet(
    "fractal_memory.parquet"
)

# =====================================
# LOAD VALIDATION
# =====================================

validation = pd.read_parquet(
    "intent_validation_memory.parquet"
)

# =====================================
# LOAD CONTEXT
# =====================================

context = pd.read_parquet(
    "htf_ltf_context_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

prediction_rows = []

# =====================================
# BUILD OUTCOME MAP
# =====================================

validation_map = validation.set_index(
    "timestamp"
)

# =====================================
# LOOP MEMORY
# =====================================

for _, row in memory.iterrows():

    signature = row[
        "pattern_signature"
    ]

    strength = float(
        row["strength"]
    )

    occurrences = int(
        row["occurrences"]
    )

    matching_context = context[

        context[
            "contextual_alignment"
        ]
        .astype(str)
        .str.contains(

            signature.split(
                " -> "
            )[-1]

        )

    ]

    # =====================================
    # STORAGE
    # =====================================

    future_outcomes = []

    # =====================================
    # LOOP MATCHES
    # =====================================

    for _, ctx in matching_context.iterrows():

        timestamp = ctx["timestamp"]

        if timestamp in validation_map.index:

            outcome = str(

                validation_map.loc[
                    timestamp
                ]["outcome"]

            )

            future_outcomes.append(
                outcome
            )

    # =====================================
    # NO OUTCOMES
    # =====================================

    if len(future_outcomes) == 0:

        dominant_outcome = (
            "unknown"
        )

        predictive_confidence = 0

    else:

        outcome_counts = pd.Series(

            future_outcomes

        ).value_counts()

        dominant_outcome = str(

            outcome_counts.index[0]

        )

        predictive_confidence = float(

            outcome_counts.iloc[0]
            /
            len(future_outcomes)

        )

    predictive_confidence = round(
        predictive_confidence,
        4
    )

    # =====================================
    # PREDICTIVE SCORE
    # =====================================

    predictive_score = round(

        predictive_confidence
        *
        strength
        *
        np.log1p(
            occurrences
        ),

        4

    )

    # =====================================
    # SAVE
    # =====================================

    prediction_rows.append({

        "pattern_signature":
            signature,

        "occurrences":
            occurrences,

        "dominant_outcome":
            dominant_outcome,

        "predictive_confidence":
            predictive_confidence,

        "pattern_strength":
            strength,

        "predictive_score":
            predictive_score

    })

# =====================================
# BUILD DF
# =====================================

prediction_df = pd.DataFrame(
    prediction_rows
)

# =====================================
# SORT
# =====================================

prediction_df = prediction_df.sort_values(

    "predictive_score",

    ascending=False

)

# =====================================
# SAVE
# =====================================

prediction_df.to_parquet(

    "predictive_sequence_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("TOP PREDICTIVE STRUCTURES")

print("=" * 50)

print()

print(
    prediction_df.head(30)
)

print()

print("TOTAL PREDICTIVE PATTERNS:")

print(
    len(prediction_df)
)

print()

print("MEMORY SAVED:")

print(
    "predictive_sequence_memory.parquet"
)

print()
