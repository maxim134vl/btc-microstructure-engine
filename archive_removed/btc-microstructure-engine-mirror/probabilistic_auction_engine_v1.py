import pandas as pd
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

    # -------------------------------------

    try:

        old = pd.read_parquet(
            "probabilistic_auction_memory.parquet"
        )

        row = pd.concat([
            old,
            row
        ])

    except:

        pass

    # -------------------------------------

    row.to_parquet(
        "probabilistic_auction_memory.parquet",
        index=False
    )

    print()

    print(
        "MEMORY SAVED:"
    )

    print(
        "probabilistic_auction_memory.parquet"
    )

if __name__ == "__main__":

    run()
