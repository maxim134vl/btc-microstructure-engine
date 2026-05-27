import pandas as pd
import numpy as np

from datetime import datetime
from state_manager_v1 import STATE
def run():

    print()

    print(
        "AUCTION REINFORCEMENT ENGINE"
    )

    print()

    # =====================================
    # LOAD
    # =====================================

    synthesis = STATE[
        "auction_synthesis"
    ]

    convergence = STATE[
        "auction_convergence"
    ]

    latest_synthesis = (
        synthesis.iloc[-1]
    )

    # =====================================
    # RUNTIME COGNITION
    # =====================================

    runtime_cognition = STATE.get(
        "runtime_cognition",
        {}
    )

    persistence_score = float(

        runtime_cognition.get(
            "persistence_score",
            0
        )

    )

    structural_rank = runtime_cognition.get(
        "structural_rank",
        "LOW"
    )

    synthesis_state = runtime_cognition.get(
        "synthesis_state",
        "NONE"
    )

    alignment_score = float(

        runtime_cognition.get(
            "alignment_score",
            0.25
        )

    )

    location_bias = runtime_cognition.get(
        "location_bias",
        "NEUTRAL"

    )

    # =====================================
    # MEMORY
    # =====================================

    try:

        memory = pd.read_parquet(
            "auction_reinforcement_memory.parquet"
        )

    except:

        memory = pd.DataFrame()

    # =====================================
    # EXTRACT
    # =====================================

    auction_state = latest_synthesis[
        "auction_state"
    ]

    latest_synthesis = synthesis.iloc[-1]

    volume_response = STATE[
        "volume_response"
    ]

    latest_response = (
        volume_response.iloc[-1]
    )

    volume_event = latest_response.get(
        "volume_event",
        "NEUTRAL"
    )

    effort_result_state = latest_response.get(
        "effort_result_state",
        "NEUTRAL"
    )

    localized_behavior = latest_response.get(
        "localized_behavior",
        "neutral"
    )

    unfinished_auction = bool(

        latest_response.get(
            "unfinished_auction",
            False
        )

    )

    # =====================================
    # INITIAL BELIEF
    # =====================================

    belief_strength = 0.5

    # -------------------------------------
    # ABSORPTION
    # -------------------------------------

    if effort_result_state == (
        "ABSORPTION_RESPONSE"
    ):

        belief_strength += 0.15

    # -------------------------------------
    # UNFINISHED AUCTION
    # -------------------------------------

    if unfinished_auction == True:

        belief_strength += 0.1

    # -------------------------------------
    # DISTRIBUTION
    # -------------------------------------

    if localized_behavior == (
        "localized_distribution"
    ):

        belief_strength += 0.1

    # -------------------------------------
    # STRUCTURAL CONTEXT
    # -------------------------------------

    if auction_state != (
        "NEUTRAL"
    ):

        belief_strength += 0.15

    # -------------------------------------
    # COGNITION PERSISTENCE
    # -------------------------------------

    belief_strength += (
        persistence_score * 0.2
    )

    # -------------------------------------
    # STRUCTURAL RANK
    # -------------------------------------

    if structural_rank == "HIGH":

        belief_strength += 0.15

    # -------------------------------------
    # EXHAUSTION PENALTY
    # -------------------------------------

    if synthesis_state == (
        "LOCAL_EXHAUSTION"
    ):

        belief_strength -= 0.2

    # -------------------------------------
    # MTF ALIGNMENT
    # -------------------------------------

    belief_strength += (
        alignment_score * 0.25
    )

    # -------------------------------------
    # LOCATION BIAS
    # -------------------------------------

    if location_bias == (
        "LOWER_ABSORPTION"
    ):

        belief_strength += 0.20

    # -------------------------------------

    if location_bias == (
        "UPPER_DISTRIBUTION"
    ):

        belief_strength -= 0.15

    # -------------------------------------

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        belief_strength -= 0.10

    # -------------------------------------

    if location_bias == (
        "LOWER_CAPITULATION"
    ):

        belief_strength += 0.10

    # =====================================
    # CONFLICT SUPPRESSION
    # =====================================

    conflict_score = 0

    # -------------------------------------
    # LOW ALIGNMENT + HIGH CONVICTION
    # -------------------------------------

    if (
        alignment_score < 0.50
        and
        belief_strength > 0.75
    ):

        conflict_score += 0.20

    # -------------------------------------
    # STRUCTURAL CONFLICT
    # -------------------------------------

    if (

        structural_rank == "LOW"

        and

        belief_strength > 0.65

    ):

        conflict_score += 0.10

    # -------------------------------------
    # MID AUCTION TRANSFER
    # -------------------------------------

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        conflict_score += 0.10

    # =====================================
    # APPLY SUPPRESSION
    # =====================================

    belief_strength -= conflict_score

    # =====================================
    # DIMINISHING RETURNS
    # =====================================

    belief_strength = (

        1 -

        np.exp(

            -belief_strength

        )

    )

    # =====================================
    # NORMALIZATION
    # =====================================

    belief_strength = max(
        0,
        min(
            belief_strength,
            1
        )
    )

    # =====================================
    # BELIEF STATE
    # =====================================

    belief_state = (
        "NEUTRAL_CONVICTION"
    )

    # -------------------------------------

    if belief_strength >= 0.8:

        belief_state = (
            "HIGH_CONVICTION"
        )

    # -------------------------------------

    elif belief_strength >= 0.65:

        belief_state = (
            "MODERATE_CONVICTION"
        )

    # =====================================
    # OUTPUT
    # =====================================

    print(
        "BELIEF STATE:"
    )

    print(
        belief_state
    )

    print()

    print(
        "BELIEF STRENGTH:"
    )

    print(
        belief_strength
    )

    print()

    print(
        "AUCTION STATE:"
    )

    print(
        auction_state
    )

    print()

    # =====================================
    # SAVE
    # =====================================

    row = pd.DataFrame([{

        "auction_state":
            auction_state,

        "belief_state":
            belief_state,

        "belief_strength":
            belief_strength,

        "localized_behavior":
            localized_behavior,

        "effort_result_state":
            effort_result_state,

        "timestamp":
            datetime.utcnow(),

    }])

    memory = pd.concat([

        memory,
        row

    ])

    memory = memory.tail(100)

    memory.to_parquet(
        "auction_reinforcement_memory.parquet"
    )

    STATE["auction_reinforcement"] = (
        memory
    )

if __name__ == "__main__":

    run()
