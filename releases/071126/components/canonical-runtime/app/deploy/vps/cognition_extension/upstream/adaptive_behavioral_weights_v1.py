import pandas as pd
from storage.path_registry import resolve_read, resolve_write

print()
print("ADAPTIVE BEHAVIORAL WEIGHTS")
print()

# =====================================
# LOAD REPLAY
# =====================================

try:

    replay = pd.read_parquet(
        resolve_read("behavioral_replay_memory.parquet")
    )

except:

    replay = pd.DataFrame()

# =====================================
# DEFAULT WEIGHTS
# =====================================

weights = {

    "EXHAUSTION_SEQUENCE": 0.95,

    "ABSORPTION_SEQUENCE": 0.85,

    "FAILED_CONTINUATION_SEQUENCE": 0.90,

    "NEUTRAL": 0.50
}

# =====================================
# ADAPTIVE CALIBRATION
# =====================================

if len(replay) > 0:

    for sequence in replay[
        "sequence"
    ].unique():

        subset = replay[
            replay[
                "sequence"
            ] == sequence
        ]

        success_rate = (

            len(

                subset[
                    subset[
                        "outcome"
                    ] != "NEUTRAL"
                ]

            )

            /

            len(subset)

        )

        weights[
            sequence
        ] = round(
            success_rate,
            2
        )

# =====================================
# SAVE
# =====================================

df = pd.DataFrame([weights])

df.to_parquet(
    resolve_write("adaptive_behavioral_weights.parquet")
)

# =====================================
# OUTPUT
# =====================================

print(df)

print()
