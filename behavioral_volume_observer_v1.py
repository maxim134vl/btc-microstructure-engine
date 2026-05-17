import pandas as pd

print()
print(
    "BEHAVIORAL VOLUME OBSERVER"
)
print()

# =====================================
# LOAD CONTEXT
# =====================================

context = pd.read_parquet(
    "contextual_memory_state.parquet"
)

temporal = pd.read_parquet(
    "temporal_context_memory.parquet"
)

localization = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

reactions = pd.read_parquet(
    "volume_reactions.parquet"
)

behavioral_events = pd.read_parquet(
    "behavioral_events_memory.parquet"
)

sequence_memory = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

adaptive_weights = pd.read_parquet(
    "adaptive_behavioral_weights.parquet"
)

weights = adaptive_weights.iloc[-1]

# =====================================
# LATEST STATES
# =====================================

latest_context = context.iloc[-1]

latest_temporal = temporal.iloc[-1]

latest_localization = (
    localization.iloc[-1]
)

latest_reaction = (
    reactions.iloc[-1]
)

latest_behavior = (
    behavioral_events.iloc[-1]
)

latest_sequence = (
    sequence_memory.iloc[-1]
)

# =====================================
# EXTRACT
# =====================================

regime = latest_context[
    "regime_state"
]

reaction = latest_context[
    "reaction_state"
]

volume = latest_context[
    "volume_state"
]

acceptance = latest_context[
    "acceptance_state"
]

event_state = latest_temporal[
    "event_state"
]

localized_behavior = (
    latest_localization[
        "behavior"
    ]
)

delta = latest_reaction[
    "delta"
]

delta_efficiency = (
    latest_reaction[
        "delta_efficiency"
    ]
)

volume_efficiency = (
    latest_reaction[
        "delta_efficiency"
    ]
)

behavioral_event = (
    latest_behavior[
        "event_type"
    ]
)

sequence_type = (
    latest_sequence[
        "sequence"
    ]
)

sequence_persistence = (
    latest_sequence[
        "persistence"
    ]
)

weights = adaptive_weights.iloc[-1]

# =====================================
# NARRATIVE
# =====================================

narrative = []

pressure_commentary = []

behavior_scores = {}

market_phase = (
    "BALANCED_AUCTION"
)

# -------------------------------------

if event_state == (
    "FAILED_LIQUIDITY_CASCADE"
):

    narrative.append(

        "Liquidity failures continue "
        "expanding through the auction."
    )

# -------------------------------------

if event_state == (
    "FAILED_CONTINUATION"
):

    narrative.append(

        "Directional continuation "
        "is weakening."
    )

# -------------------------------------

if event_state == (
    "LINGERING_WEAKNESS"
):

    narrative.append(

        "Previous imbalance still "
        "affects current auction behavior."
    )

# -------------------------------------

if reaction == "EXHAUSTION":

    narrative.append(

        "Aggressive activity is losing "
        "efficiency."
    )

# -------------------------------------

if volume == (
    "REJECTION_FROM_MEMORY"
):

    narrative.append(

        "Auction continues rejecting "
        "prior liquidity zones."
    )

# -------------------------------------

if acceptance == (
    "FAILED_ACCEPTANCE"
):

    narrative.append(

        "Price acceptance remains unstable."
    )

# -------------------------------------

if localized_behavior == (
    "localized_absorption"
):

    if reaction == "EXHAUSTION":

        narrative.append(

            "Localized absorption appears "
            "while aggressive activity "
            "loses efficiency."
        )

    elif event_state == (
        "FAILED_LIQUIDITY_CASCADE"
    ):

        narrative.append(

            "Absorption behavior emerges "
            "inside an active liquidity "
            "failure sequence."
        )

    else:

        narrative.append(

            "Localized absorption continues "
            "appearing inside the auction."
        )

# -------------------------------------

if localized_behavior == (
    "localized_distribution"
):

    if event_state == (
        "FAILED_CONTINUATION"
    ):

        narrative.append(

            "Localized distribution appears "
            "after failed continuation, "
            "suggesting the auction is "
            "transitioning away from "
            "directional imbalance."
        )

    elif event_state == (
        "LINGERING_WEAKNESS"
    ):

        narrative.append(

            "Distribution behavior persists "
            "during lingering weakness, "
            "suggesting gradual inventory "
            "rebalancing."
        )

    else:

        narrative.append(

            "Volume distribution suggests "
            "inventory transfer behavior."
        )

# =====================================
# EFFORT VS RESULT
# =====================================

efficiency_commentary = []

# -------------------------------------
# AGGRESSION FAILURE
# -------------------------------------

efficiency_commentary.append(

        "Aggressive participation "
        "shows signs of exhaustion, "
        "as auction continuation "
        "fails to respond to effort."
    )

# -------------------------------------
# ABSORPTION LOGIC
# -------------------------------------

if (

    localized_behavior == (
        "localized_absorption"
    )

    and

    abs(delta_efficiency) < 0.5

):

    efficiency_commentary.append(

        "Passive liquidity appears "
        "to be absorbing aggressive "
        "market activity."
    )

behavior_scores[
    "exhaustion"
] = weights[
    "EXHAUSTION_SEQUENCE"
]

# -------------------------------------
# DISTRIBUTION LOGIC
# -------------------------------------

if (

    localized_behavior == (
        "localized_distribution"
    )

    and

    market_phase == (
        "BALANCED_AUCTION"
    )

):

    efficiency_commentary.append(

        "Current distribution behavior "
        "suggests inventory transfer "
        "rather than clean continuation."
    )

behavior_scores[
    "distribution"
] = 0.9

# -------------------------------------
# DELTA COLLAPSE
# -------------------------------------

if (

    abs(delta) < 15

    and

    behavioral_event == (
        "stopping"
    )

):

    efficiency_commentary.append(

        "Aggressive participation "
        "has sharply deteriorated "
        "following prior climactic activity."
    )

behavior_scores[
    "exhaustion"
] = weights[
    "EXHAUSTION_SEQUENCE"
]

# =====================================
# PRESSURE INTERPRETATION
# =====================================

if regime == (
    "BEARISH_PRESSURE"
):

    if market_phase == (
        "BALANCED_AUCTION"
    ):

        pressure_commentary.append(

            "Localized sell-side pressure "
            "is emerging, while the broader "
            "auction still remains balanced."
        )

    elif event_state == (
        "FAILED_CONTINUATION"
    ):

        pressure_commentary.append(

            "Seller aggression remains "
            "active, but continuation "
            "quality is deteriorating."
        )

    elif reaction == (
        "EXHAUSTION"
    ):

        pressure_commentary.append(

            "Bearish pressure continues "
            "losing directional efficiency."
        )

    else:

        pressure_commentary.append(

            "Sell-side pressure currently "
            "dominates the auction."
        )

behavior_scores[
    "buy_pressure"
] = 0.6

behavior_scores[
    "balanced_auction"
] = 0.8

# -------------------------------------

if regime == (
    "BULLISH_PRESSURE"
):

    if market_phase == (
        "BALANCED_AUCTION"
    ):

        pressure_commentary.append(

            "Localized buy-side pressure "
            "is emerging, although the "
            "broader auction remains "
            "relatively balanced."
        )

    elif reaction == (
        "EXHAUSTION"
    ):

        pressure_commentary.append(

            "Buy-side initiative is "
            "showing weakening efficiency."
        )

    else:

        pressure_commentary.append(

            "Buy-side pressure currently "
            "drives auction expansion."
        )

# =====================================
# MARKET PHASE
# =====================================

if event_state == (
    "FAILED_LIQUIDITY_CASCADE"
):

    market_phase = (
        "DIRECTIONAL_IMBALANCE"
    )

elif event_state == (
    "FAILED_CONTINUATION"
):

    market_phase = (
        "WEAKENING_IMBALANCE"
    )

elif event_state == (
    "LINGERING_WEAKNESS"
):

    market_phase = (
        "STABILIZING_AUCTION"
    )

# =====================================
# DEFAULT STATE
# =====================================

if len(narrative) == 0:

    narrative.append(

        "Auction currently shows "
        "no strong directional imbalance."
    )

    narrative.append(

        "Behavior remains rotational "
        "and relatively balanced."
    )

# =====================================
# DOMINANT BEHAVIOR
# =====================================

dominant_behavior = (
    max(
        behavior_scores,
        key=behavior_scores.get
    )

    if len(
        behavior_scores
    ) > 0

    else "neutral"
)

# =====================================
# SYNTHESIS
# =====================================

full_narrative = ""

if len(
    narrative
) > 0:

    first_line = (
        narrative[0]
    )

    skip_line = False

    # ---------------------------------
    # DEDUPLICATION
    # ---------------------------------

    if (

        "distribution"
        in
        first_line.lower()

    ):

        for eff in efficiency_commentary:

            if (

                "distribution"
                in
                eff.lower()

            ):

                skip_line = True

    # ---------------------------------
    # CONNECTOR
    # ---------------------------------

    if (
        "distribution"
        in
        first_line.lower()
    ):

        connector = (
            " At the same time, "
        )

    elif (
        "absorption"
        in
        first_line.lower()
    ):

        connector = (
            " Meanwhile, "
        )

    elif (
        "weakening"
        in
        first_line.lower()
    ):

        connector = (
            " In addition, "
        )

    else:

        connector = (
            " Further auction behavior "
            "suggests that "
        )

 # ---------------------------------
 # FINAL ADD
 # ---------------------------------

    if skip_line == False:

        full_narrative += (
            connector
        )

        full_narrative += (

            first_line[0].lower()

            +

            first_line[1:]

        )

# =====================================
# SEQUENCE INTERPRETATION
# =====================================

sequence_commentary = []

transition_commentary = []

# -------------------------------------

if sequence_type == (
    "EXHAUSTION_SEQUENCE"
):

    if sequence_persistence >= 3:

        sequence_commentary.append(

            "Persistent exhaustion behavior "
            "suggests continued deterioration "
            "in directional auction activity."
        )

    else:

        sequence_commentary.append(

            "Current auction behavior "
            "resembles an exhaustion "
            "sequence following failed "
            "directional continuation."
        )

# -------------------------------------

if sequence_type == (
    "FAILED_CONTINUATION_SEQUENCE"
):

    if sequence_persistence >= 3:

        sequence_commentary.append(

            "Failed continuation behavior "
            "continues reinforcing across "
            "multiple auction rotations."
        )

    else:

        sequence_commentary.append(

            "Directional activity continues "
            "losing efficiency despite "
            "ongoing aggressive participation."
        )

# -------------------------------------

if sequence_type == (
    "ABSORPTION_SEQUENCE"
):

    if sequence_persistence >= 3:

        sequence_commentary.append(

            "Persistent absorption behavior "
            "suggests ongoing passive defense "
            "inside the auction."
        )

    else:

        sequence_commentary.append(

            "Passive liquidity continues "
            "absorbing aggressive activity "
            "inside the current auction."
        )

# -------------------------------------
# TRANSITIONS
# -------------------------------------

if len(
    transition_commentary
) > 0:

    for line in transition_commentary:

        full_narrative += (
            " "
        )

        full_narrative += (
            line
        )

# -------------------------------------
# SEQUENCES
# -------------------------------------

if len(
    sequence_commentary
) > 0:

    for line in sequence_commentary:

        full_narrative += (
            " "
        )

        full_narrative += (
            line
        )

# -------------------------------------
# EFFORT VS RESULT
# -------------------------------------

if len(
    efficiency_commentary
) > 0:

    for line in efficiency_commentary:

        full_narrative += (
            " "
        )

        full_narrative += (
            line
        )

# -------------------------------------
# CONTEXTUAL NARRATIVE
# -------------------------------------

if len(
    narrative
) > 0:

    first_line = narrative[0]

    if (
        "distribution" in first_line.lower()
    ):

        connector = (
            " At the same time, "
        )

    elif (
        "absorption" in first_line.lower()
    ):

        connector = (
            " Meanwhile, "
        )

    elif (
        "weakening" in first_line.lower()
    ):

        connector = (
            " In addition, "
        )

    else:

        connector = (
            " Further auction behavior "
            "suggests that "
        )

if skip_line == False:

    full_narrative += (
        connector
    )

    full_narrative += (
        first_line[0].lower()
        +
        first_line[1:]
    )

# =====================================
# TRANSITION DETECTION
# =====================================

# -------------------------------------
# EXHAUSTION -> BALANCE
# -------------------------------------

if (

    sequence_type == (
        "EXHAUSTION_SEQUENCE"
    )

    and

    market_phase == (
        "BALANCED_AUCTION"
    )

):

    transition_commentary.append(

        "Auction behavior suggests "
        "directional activity is "
        "transitioning back toward balance."
    )

# -------------------------------------
# DISTRIBUTION INSIDE BALANCE
# -------------------------------------

if (

    localized_behavior == (
        "localized_distribution"
    )

    and

    market_phase == (
        "BALANCED_AUCTION"
    )

):

    transition_commentary.append(

        "Current auction rotation "
        "continues favoring inventory "
        "redistribution behavior."
    )

# -------------------------------------
# ABSORPTION -> DEFENSE
# -------------------------------------

if (

    localized_behavior == (
        "localized_absorption"
    )

    and

    abs(delta_efficiency) < 0.3

):

    transition_commentary.append(

        "Passive liquidity response "
        "continues limiting aggressive "
        "directional expansion."
    )

# =====================================
# EFFORT VS RESULT

# =====================================
# SAVE OBSERVER STATE
# =====================================

observer_state = pd.DataFrame([{

    "dominant_behavior":
        dominant_behavior,

    "market_phase":
        market_phase,

    "narrative":
        full_narrative

}])

observer_state.to_parquet(
    "behavioral_observer_state.parquet"
)

# =====================================
# OUTPUT
# =====================================

print(
    "DOMINANT BEHAVIOR:"
)

print(
    dominant_behavior.upper()
)

print()

print(
    "CURRENT MARKET NARRATIVE"
)

print()

print(
    full_narrative
)

print()

