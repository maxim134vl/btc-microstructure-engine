import pandas as pd
import numpy as np

print("\nAUCTION PHASE ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "unified_liquidity_memory.parquet"
)

transitions = pd.read_parquet(
    "auction_state_transitions_memory.parquet"
)

df = df.dropna(how="all").copy()

# =====================================
# STORAGE
# =====================================

phases = []

# =====================================
# LOOP
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = row["timestamp"]

    recent_transitions = transitions.loc[

        transitions["timestamp"]

        <=

        timestamp

    ].tail(5)

    # =====================================
    # COUNTERS
    # =====================================

    initiative_count = len(

        recent_transitions.loc[

            recent_transitions[
                "transition_type"
            ]

            ==

            "initiative_continuation"

        ]

    )

    passive_pullback_count = len(

        recent_transitions.loc[

            recent_transitions[
                "transition_type"
            ]

            ==

            "passive_pullback"

        ]

    )

    defended_absorption_count = len(

        recent_transitions.loc[

            recent_transitions[
                "transition_type"
            ]

            ==

            "defended_absorption"

        ]

    )

    balanced_count = len(

        recent_transitions.loc[

            recent_transitions[
                "transition_type"
            ]

            ==

            "balanced_auction"

        ]

    )

    # =====================================
    # DEFAULT
    # =====================================

    phase = "undefined"

    phase_strength = 0

    # =====================================
    # MARKUP
    # =====================================

    if (

        initiative_count >= 2

        and

        passive_pullback_count >= 1

        and

        row["trend_pressure_score"] > 0

    ):

        phase = "markup"

        phase_strength = (

            row["participation_score"]

            *

            row["directional_score"]

        )

    # =====================================
    # MARKDOWN
    # =====================================

    elif (

        initiative_count >= 2

        and

        passive_pullback_count >= 1

        and

        row["trend_pressure_score"] < 0

    ):

        phase = "markdown"

        phase_strength = (

            abs(

                row[
                    "trend_pressure_score"
                ]

            )

        )

    # =====================================
    # ACCUMULATION
    # =====================================

    elif (

        defended_absorption_count >= 1

        and

        balanced_count >= 2

        and

        row["lower_rejection_score"] > 0.2

    ):

        phase = "accumulation"

        phase_strength = (

            row["lower_rejection_score"]

            *

            row["participation_score"]

        )

    # =====================================
    # DISTRIBUTION
    # =====================================

    elif (

        defended_absorption_count >= 1

        and

        balanced_count >= 2

        and

        row["upper_rejection_score"] > 0.2

    ):

        phase = "distribution"

        phase_strength = (

            row["upper_rejection_score"]

            *

            row["participation_score"]

        )

    # =====================================
    # COMPRESSION
    # =====================================

    elif (

        balanced_count >= 3

        and

        abs(

            row["spread_score"]

        )

        < 0.5

    ):

        phase = "compression"

        phase_strength = (

            1

            -

            abs(

                row["spread_score"]

            )

        )

    # =====================================
    # EXPANSION
    # =====================================

    elif (

        abs(

            row["spread_score"]

        )

        > 1.5

        and

        row["participation_score"] > 1

    ):

        phase = "expansion"

        phase_strength = (

            abs(

                row["spread_score"]

            )

            *

            row["participation_score"]

        )

    # =====================================
    # SAVE
    # =====================================

    phase_row = {

        "timestamp": timestamp,

        "phase": phase,

        "phase_strength": phase_strength,

        "initiative_count": initiative_count,

        "passive_pullback_count": passive_pullback_count,

        "defended_absorption_count": defended_absorption_count,

        "balanced_count": balanced_count,

        "trend_pressure_score": row["trend_pressure_score"],

        "participation_score": row["participation_score"],

        "spread_score": row["spread_score"]

    }

    phases.append(
        phase_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

phases_df = pd.DataFrame(
    phases
)

# =====================================
# SAVE MEMORY
# =====================================

phases_df.to_parquet(
    "auction_phase_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("AUCTION PHASE DEBUG")

print("=" * 50)

print()

print("PHASE DISTRIBUTION:")

print(

    phases_df["phase"]

    .value_counts()

)

print()

print("LAST 30 PHASES:")

debug_cols = [

    "phase",

    "phase_strength",

    "initiative_count",

    "passive_pullback_count",

    "defended_absorption_count",

    "balanced_count",

    "trend_pressure_score",

    "participation_score",

    "spread_score"

]

print(

    phases_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "auction_phase_memory.parquet"
)

print()
