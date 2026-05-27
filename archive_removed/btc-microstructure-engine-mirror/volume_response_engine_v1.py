import pandas as pd

print()
print(
    "VOLUME RESPONSE ENGINE"
)
print()

# =====================================
# LOAD DATA
# =====================================

classification_memory = pd.read_parquet(
    "volume_classification_memory.parquet"
)

structure = pd.read_parquet(
    "candle_structure_memory.parquet"
)

latest_structure = (
    structure.iloc[-1]
)

geometry = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

localization = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

reactions = pd.read_parquet(
    "volume_reactions.parquet"
)

micro = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
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

latest_reaction = (
    reactions.iloc[-1]
)

latest_classification = (
    classification_memory.iloc[-1]
)

# =====================================
# CONTEXT WINDOWS
# =====================================

recent_local_volume = (

    localization[
        "estimated_local_volume"
    ]

    .tail(50)

)

recent_spread = (

    geometry[
        "spread"
    ]

    .tail(50)

)

recent_delta_efficiency = (

    reactions[
        "delta_efficiency"
    ]

    .tail(50)

)

# =====================================
# RELATIVE CONTEXT
# =====================================

relative_volume = (

    latest_localization[
        "estimated_local_volume"
    ]

    /

    recent_local_volume.mean()

)

relative_spread = (

    latest_geometry[
        "spread"
    ]

    /

    recent_spread.mean()

)

relative_efficiency = (

    abs(
        latest_reaction[
            "delta_efficiency"
        ]
    )

    /

    (
        recent_delta_efficiency
        .abs()
        .mean()
    )

)

# =====================================
# GEOMETRY
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

body = (
    latest_geometry[
        "body"
    ]
)

spread = (
    latest_geometry[
        "spread"
    ]
)

# =====================================
# VOLUME CLASS
# =====================================

volume_class = (
    latest_classification[
        "volume_class"
    ]
)

participation_state = (
    "NORMAL_PARTICIPATION"
)

participation_adjustment = 0

climax_state = (
    "NO_CLIMAX"
)

# =====================================
# LOCALIZED VOLUME
# =====================================

localized_behavior = (
    latest_localization[
        "behavior"
    ]
)

estimated_local_volume = (
    latest_localization[
        "estimated_local_volume"
    ]
)

volume_concentration = (
    latest_localization[
        "volume_concentration"
    ]
)

# =====================================
# REACTION
# =====================================

delta = (
    latest_structure[
        "delta"
    ]
)

delta_efficiency = (
    delta / latest_localization[
        "estimated_local_volume"
    ]
)

price_change = (
    latest_structure[
        "close"
    ] - latest_structure[
        "open"
    ]
)

# =====================================
# CLIMACTIC PARTICIPATION
# =====================================

climax_state = (
    "NO_CLIMAX"
)

participation_adjustment = 0

# -------------------------------------

if "climax" in volume_class:

    participation_state = (
        "CLIMACTIC_PARTICIPATION"
    )

    participation_adjustment = 0.5

    # ---------------------------------

    if normalized_result < 0:

        climax_state = (
            "CLIMAX_EXHAUSTION"
        )

    # ---------------------------------

    elif normalized_result > 0.5:

        climax_state = (
            "CLIMAX_CONTINUATION"
        )

    # ---------------------------------

    else:

        climax_state = (
            "CLIMAX_ABSORPTION"
        )

# =====================================
# EFFORT VS RESULT
# =====================================

effort_score = (

    (

        relative_volume

    )

    +

    (

        abs(delta_efficiency)

    )

    +

    (

        relative_spread

    )

) / 3

effort_score += (
    participation_adjustment
)

# =====================================
# RESULT QUALITY
# =====================================

close_acceptance = (

    abs(
        close_position - 0.5
    ) * 2

)

# -------------------------------------

spread_efficiency = (

    relative_spread

    *

    close_acceptance

)

# -------------------------------------

rejection_penalty = 0

if (
    upper_rejection == True
):

    rejection_penalty += 0.4

if (
    lower_rejection == True
):

    rejection_penalty += 0.4

# -------------------------------------

result_score = (

    (
        close_acceptance
    )

    +

    (
        spread_efficiency
    )

    -

    rejection_penalty

)

# -------------------------------------

effort_result_ratio = (

    result_score

    /

    (
        effort_score + 0.001
    )

)

# -------------------------------------

normalized_result = (

    effort_result_ratio

    *

    (
        1 / (
            1 +
            rejection_penalty
        )
    )

)

# =====================================
# RESPONSE ENGINE
# =====================================

volume_event = (
    "NEUTRAL_VOLUME"
)

continuation_quality = (
    "NEUTRAL"
)

# -------------------------------------
# STOPPING VOLUME
# -------------------------------------

if (

    relative_volume > 1.8

    and

    abs(delta_efficiency) < 0.3

    and

    (
        upper_rejection == True
        or
        lower_rejection == True
    )

):

    volume_event = (
        "STOPPING_VOLUME"
    )

# -------------------------------------
# ABSORPTION
# -------------------------------------

if (

    localized_behavior == (
        "localized_absorption"
    )

    and

    abs(delta_efficiency) < 0.3

):

    volume_event = (
        "ABSORPTION_VOLUME"
    )

# -------------------------------------
# CONTINUATION VOLUME
# -------------------------------------

if (

    body > (
        spread * 0.7
    )

    and

    abs(delta_efficiency) > 1.0

    and

    relative_spread > 1.5

):

    volume_event = (
        "CONTINUATION_VOLUME"
    )

# -------------------------------------
# EXHAUSTION VOLUME
# -------------------------------------

if (

    relative_volume > 2.0

    and

    abs(delta_efficiency) < 0.2

):

    volume_event = (
        "EXHAUSTION_VOLUME"
    )

# =====================================
# EFFORT RESULT INTERPRETATION
# =====================================

effort_result_state = (
    "BALANCED_RESPONSE"
)

# -------------------------------------
# ABSORPTION
# -------------------------------------

if (

    effort_score > 1.2

    and

    normalized_result < 0.6

):

    effort_result_state = (
        "ABSORPTION_RESPONSE"
    )

# -------------------------------------
# STRONG ACCEPTANCE
# -------------------------------------

elif (

    effort_score > 1.2

    and

    normalized_result > 1.0

):

    effort_result_state = (
        "EFFICIENT_CONTINUATION"
    )

# -------------------------------------
# EXHAUSTION
# -------------------------------------

elif (

    relative_volume > 2

    and

    normalized_result < 0.4

):

    effort_result_state = (
        "EXHAUSTION_RESPONSE"
    )

# =====================================
# UNFINISHED AUCTION
# =====================================

unfinished_auction = False

unfinished_reason = (
    "NONE"
)

# -------------------------------------
# HIGH EFFORT / POOR RESULT
# -------------------------------------

if (

    effort_score > 1.0

    and

    normalized_result < 0.3

):

    unfinished_auction = True

    unfinished_reason = (
        "INEFFICIENT_AUCTION"
    )

# -------------------------------------
# DISTRIBUTION WITHOUT EXPANSION
# -------------------------------------

if (

    localized_behavior == (
        "localized_distribution"
    )

    and

    relative_spread < 1.0

):

    unfinished_auction = True

    unfinished_reason = (
        "DISTRIBUTION_NOT_RESOLVED"
    )

# -------------------------------------
# REJECTION FAILURE
# -------------------------------------

if (

    (
        upper_rejection == True
        or
        lower_rejection == True
    )

    and

    abs(normalized_result) < 0.2

):

    unfinished_auction = True

    unfinished_reason = (
        "REJECTION_WITHOUT_RESOLUTION"
    )

# =====================================
# CONTINUATION QUALITY
# =====================================

if (

    volume_event == (
        "CONTINUATION_VOLUME"
    )

    and

    close_position > 0.8

):

    continuation_quality = (
        "STRONG_ACCEPTANCE"
    )

# -------------------------------------

elif (

    volume_event == (
        "CONTINUATION_VOLUME"
    )

    and

    close_position < 0.5

):

    continuation_quality = (
        "FAILED_CONTINUATION"
    )

# -------------------------------------

elif (

    volume_event == (
        "STOPPING_VOLUME"
    )

):

    continuation_quality = (
        "AUCTION_STALLED"
    )

# -------------------------------------

elif (

    volume_event == (
        "ABSORPTION_VOLUME"
    )

):

    continuation_quality = (
        "PASSIVE_DEFENSE"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "VOLUME EVENT:"
)

print(
    volume_event
)

print()

print(
    "CONTINUATION QUALITY:"
)

print(
    continuation_quality
)

print()

print(
    "VOLUME CLASS:"
)

print(
    volume_class
)

print()

print(
    "PARTICIPATION STATE:"
)

print(
    participation_state
)

print()

print(
    "RELATIVE VOLUME:"
)

print(
    round(
        relative_volume,
        2
    )
)

print()

print(
    "RELATIVE SPREAD:"
)

print(
    round(
        relative_spread,
        2
    )
)

print()

print(
    "CLIMAX STATE:"
)

print(
    climax_state
)

print()

print(
    "EFFORT SCORE:"
)

print(
    round(
        effort_score,
        2
    )
)

print()

print(
    "RESULT SCORE:"
)

print(
    round(
        result_score,
        2
    )
)

print()

print(
    "NORMALIZED RESULT:"
)

print(
    round(
        normalized_result,
        2
    )
)

print()

print(
    "EFFORT RESULT STATE:"
)

print(
    effort_result_state
)

print()

print(
    "UNFINISHED AUCTION:"
)

print(
    unfinished_auction
)

print()

print(
    "UNFINISHED REASON:"
)

print(
    unfinished_reason
)

print()

print(
    "LOCALIZED BEHAVIOR:"
)

print(
    localized_behavior
)

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "volume_event":
        volume_event,

    "continuation_quality":
        continuation_quality,

    "unfinished_auction":
        unfinished_auction,

    "unfinished_reason":
        unfinished_reason,

    "localized_behavior":
        localized_behavior,

    "delta":
        delta,

    "delta_efficiency":
        delta_efficiency,

    "estimated_local_volume":
        estimated_local_volume,

    "effort_score":
        effort_score,

    "result_score":
        result_score,

    "effort_result_ratio":
        effort_result_ratio,

    "normalized_result":
        normalized_result,

    "effort_result_state":
        effort_result_state,

    "volume_class":
        volume_class,

    "climax_state":
        climax_state,

    "participation_state":
        participation_state,

}])

row.to_parquet(
    "volume_reactions.parquet"
)
