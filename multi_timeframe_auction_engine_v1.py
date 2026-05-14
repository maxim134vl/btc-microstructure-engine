import pandas as pd
import numpy as np

print("\nMULTI TIMEFRAME AUCTION ENGINE STARTED\n")

# =====================================
# LOAD MEMORIES
# =====================================

local_df = pd.read_parquet(
    "temporal_persistence_memory.parquet"
)

global_df = pd.read_parquet(
    "behavioral_scoring_memory.parquet"
)

local_df = local_df.dropna(how="all").copy()
global_df = global_df.dropna(how="all").copy()

# =====================================
# BUILD HIGHER TIMEFRAME
# =====================================

htf = global_df.resample(
    "1h"
).agg({

    "spread_score": "mean",

    "volume_score": "mean",

    "participation_score": "mean",

    "trend_pressure_score": "mean",

    "lower_rejection_score": "mean",

    "upper_rejection_score": "mean"

})

htf = htf.dropna()

# =====================================
# HTF PHASE ESTIMATION
# =====================================

htf["htf_markup_strength"] = (

    np.maximum(
        htf["trend_pressure_score"],
        0
    )

    *

    htf["participation_score"]

)

htf["htf_markdown_strength"] = (

    abs(
        np.minimum(
            htf["trend_pressure_score"],
            0
        )
    )

    *

    htf["participation_score"]

)

htf["htf_accumulation_strength"] = (

    htf["lower_rejection_score"]

    *

    htf["participation_score"]

)

htf["htf_distribution_strength"] = (

    htf["upper_rejection_score"]

    *

    htf["participation_score"]

)

# =====================================
# DOMINANT HTF STATE
# =====================================

htf_states = []

for idx, row in htf.iterrows():

    scores = {

        "markup": row[
            "htf_markup_strength"
        ],

        "markdown": row[
            "htf_markdown_strength"
        ],

        "accumulation": row[
            "htf_accumulation_strength"
        ],

        "distribution": row[
            "htf_distribution_strength"
        ]

    }

    dominant_state = max(
        scores,
        key=scores.get
    )

    dominant_strength = scores[
        dominant_state
    ]

    htf_states.append({

        "timestamp": idx,

        "htf_phase": dominant_state,

        "htf_strength": dominant_strength

    })

htf_states_df = pd.DataFrame(
    htf_states
)

# =====================================
# ALIGNMENT ANALYSIS
# =====================================

results = []

for i in range(len(local_df)):

    local_row = local_df.iloc[i]

    timestamp = local_row["timestamp"]

    nearest_htf = htf_states_df.loc[
        htf_states_df["timestamp"] <= timestamp
    ]

    if len(nearest_htf) == 0:

        continue

    htf_row = nearest_htf.iloc[-1]

    local_phase = local_row[
        "dominant_persistent_phase"
    ]

    htf_phase = htf_row[
        "htf_phase"
    ]

    # =====================================
    # CLEAN PHASE NAMES
    # =====================================

    local_phase_clean = (

        local_phase

        .replace("_probability", "")

    )

    # =====================================
    # ALIGNMENT
    # =====================================

    aligned = (

        local_phase_clean

        ==

        htf_phase

    )

    # =====================================
    # REGIME CONFLICT
    # =====================================

    conflict = False

    if (

        local_phase_clean == "markup"

        and

        htf_phase == "markdown"

    ):

        conflict = True

    if (

        local_phase_clean == "markdown"

        and

        htf_phase == "markup"

    ):

        conflict = True

    # =====================================
    # NESTED STRUCTURE
    # =====================================

    nested_accumulation = (

        local_phase_clean

        == "accumulation"

        and

        htf_phase == "markup"

    )

    nested_distribution = (

        local_phase_clean

        == "distribution"

        and

        htf_phase == "markdown"

    )

    # =====================================
    # SAVE
    # =====================================

    result = {

        "timestamp": timestamp,

        "local_phase": local_phase_clean,

        "htf_phase": htf_phase,

        "aligned": aligned,

        "conflict": conflict,

        "nested_accumulation": nested_accumulation,

        "nested_distribution": nested_distribution,

        "local_strength": local_row[
            "dominant_persistent_value"
        ],

        "htf_strength": htf_row[
            "htf_strength"
        ]

    }

    results.append(result)

# =====================================
# BUILD DATAFRAME
# =====================================

results_df = pd.DataFrame(
    results
)

# =====================================
# SAVE MEMORY
# =====================================

results_df.to_parquet(
    "multi_timeframe_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("MULTI TIMEFRAME DEBUG")

print("=" * 50)

print()

print("LOCAL vs HTF ALIGNMENT:")

print(

    results_df["aligned"]

    .value_counts()

)

print()

print("REGIME CONFLICTS:")

print(

    results_df["conflict"]

    .value_counts()

)

print()

print("LAST 30 STRUCTURES:")

debug_cols = [

    "local_phase",

    "htf_phase",

    "aligned",

    "conflict",

    "nested_accumulation",

    "nested_distribution",

    "local_strength",

    "htf_strength"

]

print(

    results_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "multi_timeframe_memory.parquet"
)

print()
