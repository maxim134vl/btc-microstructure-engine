import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

from datetime import datetime
from state_manager_v1 import STATE

def run():

    print()

    print(
        "PROBABILISTIC AUCTION ENGINE"
    )
    
    print()

    # =====================================
    # LOAD
    # =====================================

    reinforcement = STATE[
        "auction_reinforcement"
    ]

    latest = reinforcement.iloc[-1]

    # =====================================
    # RUNTIME COGNITION
    # =====================================
 
    runtime_cognition = STATE.get(
        "runtime_cognition",
        {}
    )

    synthesis_state = runtime_cognition.get(
        "synthesis_state",
        "NONE"
    )

    persistence_score = float(
        runtime_cognition.get(
            "persistence_score",
            0
        )
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

    structural_rank = runtime_cognition.get(
        "structural_rank",
        "LOW"
    )

    # =====================================
    # MEMORY WINDOW
    # =====================================

    window = reinforcement.tail(25)

    # =====================================
    # COUNTS
    # =====================================

    absorption_count = len(

        window[

            window[
                "effort_result_state"
            ] == (
                "ABSORPTION_RESPONSE"
            )

        ]

    )

    distribution_count = len(

        window[

            window[
                "localized_behavior"
            ] == (
                "localized_distribution"
            )

        ]

    )

    high_conviction_count = len(

        window[

            window[
                "belief_state"
            ] == (
                "HIGH_CONVICTION"
        )

        ]

    )

    # =====================================
    # PROBABILITIES
    # =====================================

    absorption_probability = (

        absorption_count

        /

        len(window)

    )

    distribution_probability = (

        distribution_count

        /

        len(window)

    )

    conviction_probability = (

        high_conviction_count

        /

        len(window)

    )

    # =====================================
    # AUCTION REGIME
    # =====================================

    auction_regime = (
        "UNCERTAIN"
        )

    # -------------------------------------

    if (

        distribution_probability > 0.6

        ):

        auction_regime = (
            "DISTRIBUTION_REGIME"
        )

    # -------------------------------------

    if (

        absorption_probability > 0.5

        ):

        auction_regime = (
            "ABSORPTION_REGIME"
        )

    # -------------------------------------

    if (

        conviction_probability > 0.7

        ):

        auction_regime = (
            "HIGH_CONVICTION_AUCTION"
        )

    # =====================================
    # NORMALIZATION
    # =====================================

    absorption_probability = min(
        absorption_probability,
        1
    )

    distribution_probability = min(
        distribution_probability,
        1
    )

    conviction_probability = min(
        conviction_probability,
        1
    )

    # =====================================
    # COGNITION ADJUSTMENTS
    # =====================================

    if (

        synthesis_state
        ==
        "LOCAL_EXHAUSTION"

    ):

        conviction_probability *= 0.7

    # -------------------------------------

    if (

        structural_rank
        ==
        "HIGH"

    ):

        conviction_probability *= 1.25

    # -------------------------------------

    if persistence_score > 0.7:

        auction_regime = (
           "STRUCTURAL_REGIME"
        )

    # -------------------------------------
    # MTF ALIGNMENT
    # -------------------------------------

    conviction_probability *= (
        1 + alignment_score
    )

    # -------------------------------------
    # LOCATION BIAS
    # -------------------------------------

    if location_bias == (
        "LOWER_ABSORPTION"
    ):

        absorption_probability *= 1.25

        conviction_probability *= 1.15

    # -------------------------------------

    if location_bias == (
        "UPPER_DISTRIBUTION"
    ):

        conviction_probability *= 0.75

    # -------------------------------------

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        conviction_probability *= 0.85

    # -------------------------------------

    if location_bias == (
        "LOWER_CAPITULATION"
    ):

        absorption_probability *= 1.10

    # =====================================
    # INTERPRETATION
    # =====================================

    interpretation = []

    # -------------------------------------

    if absorption_probability > 0.4:

        interpretation.append(

            "Probability of passive "
            "absorption behavior "
            "continues increasing."
        )

    # -------------------------------------

    if distribution_probability > 0.5:

        interpretation.append(

            "Auction continues exhibiting "
            "persistent inventory "
            "distribution characteristics."
        )

    # -------------------------------------

    if conviction_probability > 0.7:

        interpretation.append(

            "Behavioral structure "
            "is becoming increasingly "
            "self-reinforcing."
        )

    # =====================================
    # FINAL NORMALIZATION
    # =====================================

    absorption_probability = min(
        absorption_probability,
        1.0
    )

    distribution_probability = min(
        distribution_probability,
        1.0
    )

    conviction_probability = min(
        conviction_probability,
        1.0
    )

    # =====================================
    # OUTPUT
    # =====================================

    print(
        "AUCTION REGIME:"
    )

    print(
        auction_regime
    )

    print()

    print(
        "ABSORPTION PROBABILITY:"
    )

    print(
        round(
            absorption_probability,
            2
        )
    )

    print()

    print(
        "DISTRIBUTION PROBABILITY:"
    )

    print(
        round(
            distribution_probability,
            2
        )
    )

    print()

    print(
        "CONVICTION PROBABILITY:"
    )

    print(
        round(
            conviction_probability,
            2
        )
    )

    print()

    print(
        "INTERPRETATION"
    )

    print()

    for line in interpretation:

        print(
            "-",
            line
        )

    print()

    # =====================================
    # SAVE
    # =====================================

    from datetime import datetime

    row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "auction_regime":
        auction_regime,

    "absorption_probability":
        absorption_probability,

    "distribution_probability":
        distribution_probability,

    "conviction_probability":
        conviction_probability

    }])

    state_payload = {

        "auction_regime":
            auction_regime

    }

    if not should_persist_state(

        "probabilistic_auction_memory.parquet",

        state_payload

    ):

        print()

        print(
            "NO REGIME CHANGE"
        )

    else:

        append_state_row(

            "probabilistic_auction_memory.parquet",

            row

        )

        print()

        print(
            "MEMORY SAVED:"
        )

        print(
            "probabilistic_auction_memory.parquet"
        )

# =====================================
# START
# =====================================

if __name__ == "__main__":
    run()
