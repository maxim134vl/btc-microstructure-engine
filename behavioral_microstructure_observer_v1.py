import pandas as pd

print()
print(
    "BEHAVIORAL MICROSTRUCTURE OBSERVER"
)
print()

# =====================================
# LOAD
# =====================================

geometry = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

localization = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

sequences = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

# =====================================
# LATEST
# =====================================

latest_geometry = (
    geometry.iloc[-1]
)

latest_localization = (
    localization.iloc[-1]
)

latest_sequence = (
    sequences.iloc[-1]
)

# =====================================
# EXTRACT GEOMETRY
# =====================================

upper_rejection = (
    latest_geometry[
        "upper_rejection"
    ]
)

lower_rejection = (
    latest_geometry[
        "lower_rejection"
    ]
)

close_position = (
    latest_geometry[
        "close_position"
    ]
)

spread_zscore = (
    latest_geometry[
        "spread_zscore"
    ]
)

structure_label = (
    latest_geometry[
        "structure_label"
    ]
)

# =====================================
# LOCALIZATION
# =====================================

localized_behavior = (
    latest_localization[
        "behavior"
    ]
)

volume_concentration = (
    latest_localization[
        "volume_concentration"
    ]
)

estimated_local_volume = (
    latest_localization[
        "estimated_local_volume"
    ]
)

# =====================================
# SEQUENCE
# =====================================

sequence = (
    latest_sequence[
        "sequence"
    ]
)

persistence = (
    latest_sequence[
        "persistence"
    ]
)

# =====================================
# NARRATIVE
# =====================================

narrative = []

# -------------------------------------
# UPPER REJECTION
# -------------------------------------

if upper_rejection == True:

    narrative.append(

        "Upper auction rejection "
        "suggests responsive sell-side "
        "activity near highs."
    )

# -------------------------------------
# LOWER REJECTION
# -------------------------------------

if lower_rejection == True:

    narrative.append(

        "Lower auction rejection "
        "suggests responsive buy-side "
        "activity near lows."
    )

# -------------------------------------
# LOCALIZED ABSORPTION
# -------------------------------------

if localized_behavior == (
    "localized_absorption"
):

    narrative.append(

        "Localized volume absorption "
        "suggests passive liquidity "
        "is defending auction flow."
    )

# -------------------------------------
# LOCALIZED DISTRIBUTION
# -------------------------------------

if localized_behavior == (
    "localized_distribution"
):

    narrative.append(

        "Localized distribution "
        "suggests inventory transfer "
        "inside the current auction."
    )

# -------------------------------------
# EXHAUSTION
# -------------------------------------

if sequence == (
    "EXHAUSTION_SEQUENCE"
):

    narrative.append(

        "Behavioral exhaustion "
        "continues developing "
        "across recent auction rotations."
    )

# -------------------------------------
# SPREAD EXPANSION
# -------------------------------------

if spread_zscore > 2:

    narrative.append(

        "Auction volatility expansion "
        "suggests increased participation "
        "imbalance."
    )

# =====================================
# OUTPUT
# =====================================

print(
    "CURRENT AUCTION CONTEXT"
)

print()

for line in narrative:

    print(
        "-",
        line
    )

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "localized_behavior":
        localized_behavior,

    "sequence":
        sequence,

    "upper_rejection":
        upper_rejection,

    "lower_rejection":
        lower_rejection,

    "spread_zscore":
        spread_zscore,

    "volume_concentration":
        volume_concentration

}])

row.to_parquet(
    "behavioral_microstructure_state.parquet"
)
