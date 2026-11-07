import pandas as pd
import numpy as np
from state_manager_v1 import STATE
from storage.path_registry import resolve_read, resolve_write
from stage2_publication_metadata import publish_atomic_frame, read_meta_reinforcement_with_evidence, capture_meta_inputs

def run():
    
    print()

    print(
        "ADAPTIVE META COGNITION ENGINE"
    )
    print()

    # =====================================
    # LOAD
    # =====================================

    probabilistic = STATE[
        "probabilistic_auction"
    ]

    reinforcement = read_meta_reinforcement_with_evidence(
        resolve_read("auction_reinforcement_memory.parquet")
    )

    latest = probabilistic.iloc[-1]

    window = reinforcement.tail(50)

    # Optional source identities only. Original STATE/latest/window/math unchanged.
    try:
        input_lineage = capture_meta_inputs(probabilistic, reinforcement, latest, window)
    except Exception as exc:
        input_lineage = None
        import warnings
        warnings.warn('META_INPUT_LINEAGE_UNPROVEN:' + str(exc), RuntimeWarning)

    # =====================================
    # EXTRACT
    # =====================================

    absorption_probability = (
        latest[
            "absorption_probability"
        ]
    )

    distribution_probability = (
        latest[
            "distribution_probability"
        ]
    )

    conviction_probability = (
        latest[
            "conviction_probability"
        ]
    )

    # =====================================
    # ENTROPY DIVERSITY
    # =====================================

    behavior_counts = (

        window[
            "localized_behavior"
        ]

        .value_counts(
            normalize = True
        )

    )

    state_counts = (

        window[
            "auction_state"
        ]

        .value_counts(
            normalize = True
        )

    )

    # -------------------------------------

    behavior_entropy = (

        -np.sum(

            behavior_counts

            *

            np.log2(
                behavior_counts + 1e-9
            )

        )

    )

    # -------------------------------------

    state_entropy = (

        -np.sum(

            state_counts

            *

            np.log2(
                state_counts + 1e-9
            )

       )

    )

    # =====================================
    # STABILITY
    # =====================================

    if len(behavior_counts) > 1:

        behavioral_stability = (

            behavior_entropy

            /

            np.log2(
                len(behavior_counts)
            )

        )

    else:

        behavioral_stability = 0

    # -------------------------------------

    if len(state_counts) > 1:

        state_stability = (

            state_entropy

            /

            np.log2(
                len(state_counts)
            )

        )

    else:

        state_stability = 0

    # =====================================
    # OVERCONFIDENCE
    # =====================================

    overconfidence_penalty = 0

    # -------------------------------------

    if absorption_probability > 0.9:

        overconfidence_penalty += 0.15

    # -------------------------------------

    if distribution_probability > 0.9:

        overconfidence_penalty += 0.15

    # -------------------------------------

    if conviction_probability > 0.9:

        overconfidence_penalty += 0.2

    # -------------------------------------

    if behavioral_stability < 0.4:

        overconfidence_penalty += 0.2

    # =====================================
    # RECALIBRATION
    # =====================================

    recalibrated_conviction = (

        conviction_probability

        -

        overconfidence_penalty

    )

    recalibrated_conviction = max(

        0,

        min(
            recalibrated_conviction,
            1
        )

    )

    # =====================================
    # META STATE
    # =====================================

    meta_state = (
        "BALANCED_COGNITION"
    )

    # -------------------------------------

    if overconfidence_penalty > 0.4:

        meta_state = (
            "OVERCONFIDENCE_DETECTED"
        )

    # -------------------------------------

    elif recalibrated_conviction < 0.4:

        meta_state = (
            "LOW_CONFIDENCE_ENVIRONMENT"
        )

    # =====================================
    # OUTPUT
    # =====================================

    print(
        "META STATE:"
    )

    print(
        meta_state
    )

    print()

    print(
        "OVERCONFIDENCE PENALTY:"
    )

    print(
        round(
            overconfidence_penalty,
            2
        )
    )

    print()

    print(
        "RECALIBRATED CONVICTION:"
    )

    print(
        round(
            recalibrated_conviction,
            2
        )
    )

    print()

    print(
        "BEHAVIOR ENTROPY:"
    )

    print(
        round(
            behavior_entropy,
            2
        )
    )

    print()

    print(
        "STATE ENTROPY:"
    )

    print(
        round(
            state_entropy,
            2
        )
    )

    print()

    print(
        "BEHAVIORAL DIVERSITY:"
    )

    print(
        round(
            behavioral_stability,
            2
        )
    )

    print()

    # =====================================
    # SAVE
    # =====================================

    row = pd.DataFrame([{

        "meta_state":
            meta_state,

        "overconfidence_penalty":
            overconfidence_penalty,

        "recalibrated_conviction":
            recalibrated_conviction,

        "behavior_entropy":
            behavior_entropy,

        "state_entropy":
            state_entropy,

        "behavioral_stability":
            behavioral_stability,

        "state_stability":
            state_stability

    }])

    # R06: actual parent observation and publication lineage; domain math unchanged.
    from runtime_lineage import apply_lineage_metadata
    from parquet_utils import atomic_parquet_write
    row["timestamp"] = pd.to_datetime(latest["timestamp"], utc=True)
    row = apply_lineage_metadata(
        row, engine_name="adaptive_meta_cognition_engine_v1.py",
        source_parquet="probabilistic_auction_memory.parquet",
        dependency_chain=["auction_reinforcement_memory.parquet",
                          "probabilistic_auction_memory.parquet",
                          "adaptive_meta_cognition_engine_v1.py",
                          "adaptive_meta_cognition_state.parquet"],
    )
    publish_atomic_frame(row, "adaptive_meta_cognition_state.parquet", producer=__file__, writer=atomic_parquet_write, input_lineage=input_lineage)
if __name__ == "__main__":

    run()
