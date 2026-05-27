import pandas as pd
import numpy as np

print("\nPROBABILISTIC PHASE ENGINE STARTED\n")

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

phase_probabilities = []

# =====================================
# LOOP
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = row["timestamp"]

    recent_transitions = transitions.loc[
        transitions["timestamp"] <= timestamp
    ].tail(8)

    # =====================================
    # COUNTS
    # =====================================

    initiative_count = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "initiative_continuation"
        ]

    )

    passive_pullback_count = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "passive_pullback"
        ]

    )

    defended_absorption_count = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "defended_absorption"
        ]

    )

    balanced_count = len(

        recent_transitions.loc[
            recent_transitions[
                "transition_type"
            ] == "balanced_auction"
        ]

    )

    # =====================================
    # BASE SCORES
    # =====================================

    markup_score = 0
    markdown_score = 0
    accumulation_score = 0
    distribution_score = 0
    compression_score = 0
    expansion_score = 0

    # =====================================
    # MARKUP SCORE
    # =====================================

    markup_score += (
        initiative_count * 1.2
    )

    markup_score += (
        passive_pullback_count * 0.8
    )

    markup_score += max(
        row["trend_pressure_score"],
        0
    )

    markup_score += (
        row["participation_score"] * 0.5
    )

    # =====================================
    # MARKDOWN SCORE
    # =====================================

    markdown_score += (
        initiative_count * 1.2
    )

    markdown_score += (
        passive_pullback_count * 0.8
    )

    markdown_score += abs(
        min(
            row["trend_pressure_score"],
            0
        )
    )

    markdown_score += (
        row["participation_score"] * 0.5
    )

    # =====================================
    # ACCUMULATION
    # =====================================

    accumulation_score += (
        defended_absorption_count * 2
    )

    accumulation_score += (
        row["lower_rejection_score"] * 2
    )

    accumulation_score += (
        balanced_count * 0.5
    )

    # =====================================
    # DISTRIBUTION
    # =====================================

    distribution_score += (
        defended_absorption_count * 2
    )

    distribution_score += (
        row["upper_rejection_score"] * 2
    )

    distribution_score += (
        balanced_count * 0.5
    )

    # =====================================
    # COMPRESSION
    # =====================================

    compression_score += (
        balanced_count * 1.5
    )

    compression_score += max(

        0,

        1 - abs(
            row["spread_score"]
        )

    )

    # =====================================
    # EXPANSION
    # =====================================

    expansion_score += abs(
        row["spread_score"]
    )

    expansion_score += (
        row["participation_score"]
    )

    expansion_score += abs(
        row["trend_pressure_score"]
    ) * 0.5

    # =====================================
    # NORMALIZATION
    # =====================================

    scores = {

        "markup": markup_score,

        "markdown": markdown_score,

        "accumulation": accumulation_score,

        "distribution": distribution_score,

        "compression": compression_score,

        "expansion": expansion_score

    }

    total_score = sum(
        scores.values()
    ) + 0.000001

    probabilities = {

        phase: score / total_score

        for phase, score

        in scores.items()

    }

    # =====================================
    # DOMINANT PHASE
    # =====================================

    dominant_phase = max(

        probabilities,

        key=probabilities.get

    )

    dominant_probability = probabilities[
        dominant_phase
    ]

    # =====================================
    # SAVE
    # =====================================

    phase_row = {

        "timestamp": timestamp,

        "dominant_phase": dominant_phase,

        "dominant_probability": dominant_probability,

        "markup_probability": probabilities["markup"],

        "markdown_probability": probabilities["markdown"],

        "accumulation_probability": probabilities["accumulation"],

        "distribution_probability": probabilities["distribution"],

        "compression_probability": probabilities["compression"],

        "expansion_probability": probabilities["expansion"]

    }

    phase_probabilities.append(
        phase_row
    )

# =====================================
# BUILD DATAFRAME
# =====================================

phase_df = pd.DataFrame(
    phase_probabilities
)

# =====================================
# SAVE MEMORY
# =====================================

phase_df.to_parquet(
    "probabilistic_phase_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("PROBABILISTIC PHASE DEBUG")

print("=" * 50)

print()

print("DOMINANT PHASE DISTRIBUTION:")

print(

    phase_df["dominant_phase"]

    .value_counts()

)

print()

print("LAST 30 PHASE STATES:")

debug_cols = [

    "dominant_phase",

    "dominant_probability",

    "markup_probability",

    "markdown_probability",

    "accumulation_probability",

    "distribution_probability",

    "compression_probability",

    "expansion_probability"

]

print(

    phase_df[debug_cols]

    .tail(30)

)

print()

print("MEMORY SAVED:")

print(
    "probabilistic_phase_memory.parquet"
)

print()
