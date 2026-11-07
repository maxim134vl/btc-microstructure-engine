import pandas as pd
import numpy as np

print("\nTEMPORAL PERSISTENCE ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "probabilistic_phase_memory.parquet"
)

df = df.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

temporal_states = []

# =====================================
# PHASES
# =====================================

phase_columns = [

    "markup_probability",

    "markdown_probability",

    "accumulation_probability",

    "distribution_probability",

    "compression_probability",

    "expansion_probability"

]

# =====================================
# LOOP
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = row["timestamp"]

    # =====================================
    # LOOKBACK WINDOW
    # =====================================

    recent = df.iloc[
        max(0, i - 10): i + 1
    ]

    # =====================================
    # PERSISTENCE
    # =====================================

    persistence = {}

    for phase_col in phase_columns:

        persistence[phase_col] = (

            recent[phase_col]

            .mean()

        )

    # =====================================
    # DOMINANT PERSISTENCE
    # =====================================

    dominant_persistent_phase = max(

        persistence,

        key=persistence.get

    )

    dominant_persistent_value = persistence[
        dominant_persistent_phase
    ]

    # =====================================
    # MOMENTUM OF PHASE
    # =====================================

    phase_momentum = {}

    for phase_col in phase_columns:

        if len(recent) >= 3:

            recent_values = recent[
                phase_col
            ].tail(3)

            momentum = (

                recent_values.iloc[-1]

                -

                recent_values.iloc[0]

            )

        else:

            momentum = 0

        phase_momentum[
            phase_col
        ] = momentum

    # =====================================
    # STRENGTHENING / WEAKENING
    # =====================================

    strongest_growth_phase = max(

        phase_momentum,

        key=phase_momentum.get

    )

    strongest_decay_phase = min(

        phase_momentum,

        key=phase_momentum.get

    )

    # =====================================
    # AUCTION MATURITY
    # =====================================

    maturity_score = (

        dominant_persistent_value

        *

        len(recent)

    )

    # =====================================
    # INSTABILITY SCORE
    # =====================================

    instability_score = 0

    for phase_col in phase_columns:

        instability_score += (

            recent[phase_col]

            .std()

        )

    # =====================================
    # SAVE
    # =====================================

    temporal_row = {

        "timestamp": timestamp,

        "dominant_persistent_phase": dominant_persistent_phase,

        "dominant_persistent_value": dominant_persistent_value,

        "strongest_growth_phase": strongest_growth_phase,

        "strongest_decay_phase": strongest_decay_phase,

        "maturity_score": maturity_score,

        "instability_score": instability_score

    }

    # =====================================
    # SAVE ALL PERSISTENCE
    # =====================================

    for phase_col in phase_columns:

        temporal_row[
            f"{phase_col}_persistence"
        ] = persistence[phase_col]

        temporal_row[
            f"{phase_col}_momentum"
        ] = phase_momentum[phase_col]

    temporal_states.append(
        temporal_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

temporal_df = pd.DataFrame(
    temporal_states
)

# =====================================
# SAVE MEMORY
# =====================================

temporal_df.to_parquet(
    "temporal_persistence_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("TEMPORAL PERSISTENCE DEBUG")

print("=" * 50)

print()

print("DOMINANT PERSISTENT PHASES:")

print(

    temporal_df[
        "dominant_persistent_phase"
    ].value_counts()

)

print()

print("LAST 30 TEMPORAL STATES:")

debug_cols = [

    "dominant_persistent_phase",

    "dominant_persistent_value",

    "strongest_growth_phase",

    "strongest_decay_phase",

    "maturity_score",

    "instability_score"

]

print(

    temporal_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "temporal_persistence_memory.parquet"
)

print()
