import pandas as pd
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

    volume_event = "NEUTRAL"

    effort_result_state = "NEUTRAL"

    localized_behavior = "neutral"

    unfinished_auction = False

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

    # =====================================
    # CONVERGENCE MEMORY
    # =====================================

    recent_absorption = len(

        convergence[

            convergence[
                "effort_result_state"
            ] == (
                "ABSORPTION_RESPONSE"
            )

        ]

    )

    recent_distribution = len(

        convergence[

            convergence[
                "localized_behavior"
            ] == (
                "localized_distribution"
            )

        ]

    )

    # =====================================
    # REINFORCEMENT
    # =====================================

    if recent_absorption >= 3:

        belief_strength += 0.2

    # -------------------------------------

    if recent_distribution >= 4:

        belief_strength += 0.2

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
            effort_result_state

    }])

    memory = pd.concat([

        memory,
        row

    ])

    memory = memory.tail(100)

    memory.to_parquet(
        "auction_reinforcement_memory.parquet"
    )

if __name__ == "__main__":

    run()
