import math

import pandas as pd

from calibration_diagnostics import (
    DIAGNOSTIC_EXPORT_COLUMNS,
    build_diagnostic_exports,
)
from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

from datetime import datetime
from runtime_integrity import (
    ALIGNMENT_STATUS_VALID,
    log_runtime_warning,
)
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE


def _belief_entropy(window: pd.DataFrame) -> float:
    if len(window) == 0 or "belief_state" not in window.columns:
        return 0.0

    counts = window["belief_state"].value_counts(normalize=True)
    entropy = 0.0
    for probability in counts:
        if probability > 0:
            entropy -= probability * math.log(probability)
    return entropy


def _resolve_alignment(runtime_cognition: dict) -> tuple:
    alignment_status = runtime_cognition.get(
        "alignment_status",
        "MISSING",
    )
    raw_alignment = runtime_cognition.get("alignment_score")

    if alignment_status == ALIGNMENT_STATUS_VALID and raw_alignment is not None:
        score = float(raw_alignment)
        return score, alignment_status, 1.0 + score

    log_runtime_warning(
        f"Probabilistic skipped alignment multiplier "
        f"(status={alignment_status})"
    )
    return None, alignment_status, 1.0


def run():

    print()

    print(
        "PROBABILISTIC AUCTION ENGINE"
    )
    
    print()

    reinforcement = STATE[
        "auction_reinforcement"
    ]

    latest = reinforcement.iloc[-1]

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

    alignment_score, alignment_status, alignment_component = (
        _resolve_alignment(runtime_cognition)
    )

    location_bias = runtime_cognition.get(
        "location_bias",
        "NEUTRAL"
    )

    structural_rank = runtime_cognition.get(
        "structural_rank",
        "LOW"
    )

    window = reinforcement.tail(25)

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

    reinforcement_component = conviction_probability

    auction_regime = (
        "UNCERTAIN"
        )

    if (

        distribution_probability > 0.6

        ):

        auction_regime = (
            "DISTRIBUTION_REGIME"
        )

    if (

        absorption_probability > 0.5

        ):

        auction_regime = (
            "ABSORPTION_REGIME"
        )

    if (

        conviction_probability > 0.7

        ):

        auction_regime = (
            "HIGH_CONVICTION_AUCTION"
        )

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

    if (

        synthesis_state
        ==
        "LOCAL_EXHAUSTION"

    ):

        conviction_probability *= 0.7

    if (

        structural_rank
        ==
        "HIGH"

    ):

        conviction_probability *= 1.25

    persistence_component = persistence_score

    if persistence_score > 0.7:

        auction_regime = (
           "STRUCTURAL_REGIME"
        )

    if alignment_status == ALIGNMENT_STATUS_VALID:
        conviction_probability *= alignment_component

    location_component = 1.0

    if location_bias == (
        "LOWER_ABSORPTION"
    ):

        absorption_probability *= 1.25

        conviction_probability *= 1.15
        location_component *= 1.15

    if location_bias == (
        "UPPER_DISTRIBUTION"
    ):

        conviction_probability *= 0.75
        location_component *= 0.75

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        conviction_probability *= 0.85
        location_component *= 0.85

    if location_bias == (
        "LOWER_CAPITULATION"
    ):

        absorption_probability *= 1.10

    volume_response = STATE.get("volume_response")
    unfinished_auction_component = 0.0
    if volume_response is not None and len(volume_response) > 0:
        unfinished_auction_component = float(
            bool(
                volume_response.iloc[-1].get(
                    "unfinished_auction",
                    False,
                )
            )
        )

    entropy_penalty = _belief_entropy(window)

    conflict_penalty = float(
        latest.get(
            "conflict_penalty",
            0.0,
        )
    )

    interpretation = []

    if absorption_probability > 0.4:

        interpretation.append(

            "Probability of passive "
            "absorption behavior "
            "continues increasing."
        )

    if distribution_probability > 0.5:

        interpretation.append(

            "Auction continues exhibiting "
            "persistent inventory "
            "distribution characteristics."
        )

    if conviction_probability > 0.7:

        interpretation.append(

            "Behavioral structure "
            "is becoming increasingly "
            "self-reinforcing."
        )

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

    raw_conviction = conviction_probability

    probabilistic_history = safe_read_parquet(
        "probabilistic_auction_memory.parquet"
    )

    current_snapshot = {
        "auction_regime": auction_regime,
        "absorption_probability": absorption_probability,
        "distribution_probability": distribution_probability,
        "conviction_probability": conviction_probability,
        "raw_conviction": raw_conviction,
        "alignment_status": alignment_status,
        "alignment_component": alignment_component,
        "persistence_component": persistence_component,
        "location_component": location_component,
        "unfinished_auction_component": unfinished_auction_component,
        "entropy_penalty": entropy_penalty,
        "conflict_penalty": conflict_penalty,
        "reinforcement_component": reinforcement_component,
    }

    diagnostic_exports = build_diagnostic_exports(
        probabilistic_history=probabilistic_history,
        reinforcement_history=reinforcement,
        reinforcement_window=window,
        runtime_cognition=runtime_cognition,
        current_row=current_snapshot,
    )

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
        conviction_probability,

    "alignment_status":
        alignment_status,

    "alignment_component":
        alignment_component,

    "persistence_component":
        persistence_component,

    "location_component":
        location_component,

    "unfinished_auction_component":
        unfinished_auction_component,

    "entropy_penalty":
        entropy_penalty,

    "conflict_penalty":
        conflict_penalty,

    "reinforcement_component":
        reinforcement_component,

    **diagnostic_exports,

    }])

    row = apply_lineage_metadata(
        row,
        engine_name="probabilistic_auction_engine_v1.py",
        source_parquet="auction_reinforcement_memory.parquet",
        dependency_chain=[
            "runtime_cognition_memory.parquet",
            "auction_reinforcement_memory.parquet",
            "probabilistic_auction_engine_v1.py",
            "probabilistic_auction_memory.parquet",
        ],
        event_timestamp_col="timestamp",
    )

    state_payload = {

        "auction_regime":
            auction_regime,

        "alignment_status":
            alignment_status,

        "alignment_component":
            alignment_component,

        "persistence_component":
            persistence_component,

        "location_component":
            location_component,

        "unfinished_auction_component":
            unfinished_auction_component,

        "entropy_penalty":
            entropy_penalty,

        "conflict_penalty":
            conflict_penalty,

        "reinforcement_component":
            reinforcement_component,

        **{
            key: diagnostic_exports[key]
            for key in DIAGNOSTIC_EXPORT_COLUMNS
        },

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


if __name__ == "__main__":
    run()
