import pandas as pd
import numpy as np
import os

print("\nFRACTAL MEMORY ENGINE STARTED\n")

# =====================================
# LOAD CONTEXT
# =====================================

context = pd.read_parquet(
    "htf_ltf_context_memory.parquet"
)

# =====================================
# LOAD EXISTING MEMORY
# =====================================

if os.path.exists(
    "fractal_memory.parquet"
):

    memory = pd.read_parquet(
        "fractal_memory.parquet"
    )

    print(
        "PREVIOUS FRACTAL MEMORY LOADED\n"
    )

else:

    memory = pd.DataFrame(

        columns=[

            "pattern_id",

            "pattern_signature",

            "occurrences",

            "last_seen",

            "strength"

        ]

    )

    print(
        "NO PREVIOUS FRACTAL MEMORY\n"
    )

# =====================================
# STORAGE
# =====================================

memory_rows = []

pattern_counter = len(memory)

# =====================================
# LOOP
# =====================================

for i in range(2, len(context)):

    current = context.iloc[i]

    previous_1 = context.iloc[i - 1]

    previous_2 = context.iloc[i - 2]

    timestamp = current[
        "timestamp"
    ]

    # =====================================
    # BUILD SIGNATURE
    # =====================================

    signature = (

        str(previous_2[
            "contextual_alignment"
        ])

        + " -> "

        + str(previous_1[
            "contextual_alignment"
        ])

        + " -> "

        + str(current[
            "contextual_alignment"
        ])

    )

    # =====================================
    # EXISTING MEMORY
    # =====================================

    existing = memory[

        memory[
            "pattern_signature"
        ]
        ==
        signature

    ]

    # =====================================
    # UPDATE EXISTING
    # =====================================

    if len(existing) > 0:

        existing_row = existing.iloc[-1]

        pattern_id = int(
            existing_row[
                "pattern_id"
            ]
        )

        occurrences = int(

            existing_row[
                "occurrences"
            ]

        ) + 1

        strength = round(

            1 + (
                occurrences
                / 10
            ),

            4

        )

    # =====================================
    # NEW PATTERN
    # =====================================

    else:

        pattern_counter += 1

        pattern_id = pattern_counter

        occurrences = 1

        strength = 1.0

    # =====================================
    # SAVE
    # =====================================

    memory_rows.append({

        "pattern_id":
            pattern_id,

        "pattern_signature":
            signature,

        "occurrences":
            occurrences,

        "last_seen":
            timestamp,

        "strength":
            strength

    })

# =====================================
# BUILD DF
# =====================================

memory_df = pd.DataFrame(
    memory_rows
)

# =====================================
# KEEP LATEST VERSION
# =====================================

memory_df = memory_df.sort_values(
    "last_seen"
)

memory_df = memory_df.drop_duplicates(

    subset=["pattern_signature"],

    keep="last"

)

# =====================================
# SAVE
# =====================================

memory_df.to_parquet(

    "fractal_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("FRACTAL MEMORY DISTRIBUTION")

print("=" * 50)

print()

print(
    memory_df.sort_values(
        "occurrences",
        ascending=False
    ).head(20)
)

print()

print("TOTAL PATTERNS:")

print(
    len(memory_df)
)

print()

print("MEMORY SAVED:")

print(
    "fractal_memory.parquet"
)

print()
