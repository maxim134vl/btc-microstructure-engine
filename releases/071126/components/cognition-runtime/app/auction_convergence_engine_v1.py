import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

from datetime import datetime

def run():

    print()
    print(
        "AUCTION CONVERGENCE ENGINE"
    )
    print()

    # =====================================
    # LOAD
    # =====================================

    response = safe_read_parquet(
        "volume_response_state.parquet"
    )

    if response is None or len(response) == 0:
        print("SKIPPED: volume_response_state.parquet empty (cold start)")
        print()
        return

    latest = response.iloc[-1]

    # =====================================
    # MEMORY
    # =====================================

    try:

        memory = safe_read_parquet(
            "auction_convergence_memory.parquet"
        )

    except:

        memory = pd.DataFrame()

    # =====================================
    # EXTRACT
    # =====================================

    volume_event = (
        latest[
            "volume_event"
        ]
    )

    effort_result_state = (
        latest[
            "effort_result_state"
        ]
    )

    unfinished_auction = (
        latest[
            "unfinished_auction"
        ]
    )

    unfinished_reason = (
        latest[
            "unfinished_reason"
        ]
    )

    localized_behavior = (
        latest[
            "localized_behavior"
        ]
    )

    # =====================================
    # BUILD EVENT
    # =====================================

    current_event = {

        "volume_event":
            volume_event,

        "effort_result_state":
            effort_result_state,

        "unfinished_auction":
            unfinished_auction,

        "unfinished_reason":
            unfinished_reason,

        "localized_behavior":
            localized_behavior

    }

    # =====================================
    # APPEND MEMORY
    # =====================================

    memory = pd.concat([

        memory,

        pd.DataFrame([current_event])

    ])

    # =====================================
    # KEEP WINDOW
    # =====================================

    memory = memory.tail(10)

    # =====================================
    # CONVERGENCE
    # =====================================

    convergence_state = (
        "NEUTRAL"
    )

    # -------------------------------------
    # ABSORPTION CHAIN
    # -------------------------------------

    absorption_count = len(

        memory[

            memory[
                "effort_result_state"
            ] == (
                "ABSORPTION_RESPONSE"
            )

        ]

    )

    # -------------------------------------
    # UNFINISHED CHAIN
    # -------------------------------------

    unfinished_count = len(

        memory[

            memory[
                "unfinished_auction"
            ] == True

        ]

    )

    # -------------------------------------
    # DISTRIBUTION CHAIN 
    # -------------------------------------

    distribution_count = len(

        memory[

            memory[
                "localized_behavior"
            ] == (
                "localized_distribution"
            )

        ]

    )

    # =====================================
    # INTERPRETATION
    # =====================================

    if (

        absorption_count >= 3

    ):

        convergence_state = (
            "PERSISTENT_ABSORPTION"
        )

    # -------------------------------------

    if (

        unfinished_count >= 3

    ):

        convergence_state = (
            "UNRESOLVED_AUCTION"
        )

    # -------------------------------------

    if (

        distribution_count >= 4

    ):

        convergence_state = (
            "PERSISTENT_DISTRIBUTION"
        )

    # =====================================
    # OUTPUT
    # =====================================

    print(
        "CONVERGENCE STATE:"
    )

    print(
        convergence_state
    )

    print()

    print(
        "ABSORPTION EVENTS:"
    )

    print(
        absorption_count
    )

    print()

    print(
        "UNFINISHED AUCTIONS:"
    )

    print(
        unfinished_count
    )

    print()

    print(
        "DISTRIBUTION EVENTS:"
    )

    print(
        distribution_count
    )

    print()

    # =====================================
    # SAVE
    # =====================================
 
    row = pd.DataFrame([{

        "timestamp":
            datetime.utcnow(),

        "convergence_state":
            convergence_state,

        "unfinished_auctions":
            unfinished_count,

        "distribution_events":
            distribution_count,

        "localized_behavior":
            localized_behavior

    }])

    state_payload = {

        "convergence_state":
            convergence_state,

        "unfinished_auctions":
            unfinished_count,

        "distribution_events":
            distribution_count

    }

    append_state_row(

        "auction_convergence_memory.parquet",

        row

    )

    print()

    print(
        "MEMORY SAVED:"
    )

    print(
        "auction_convergence_memory.parquet"
    )


if __name__ == "__main__":
    run()
