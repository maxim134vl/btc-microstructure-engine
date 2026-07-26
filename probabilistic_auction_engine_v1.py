import math
import os

import pandas as pd

from calibration_diagnostics import (
    DIAGNOSTIC_EXPORT_COLUMNS,
    build_diagnostic_exports,
)
from calibration_config import get_calibration_settings
from calibration_discipline import (
    DISCIPLINE_EXPORT_COLUMNS,
    apply_probabilistic_discipline,
    resolve_runtime_conviction,
)
from adversarial_diagnostics import (
    ADVERSARIAL_EXPORT_COLUMNS,
    build_adversarial_exports,
)
from ontology_stabilization import (
    STABILIZATION_EXPORT_COLUMNS,
    build_ontology_stabilization_exports,
)
from calibration_drift_engine import (
    compute_calibration_drift,
    log_drift_warning,
)
from calibration_stability import compute_runtime_stability_exports
from regime_segmentation import infer_regime_segmentation
from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

from runtime_integrity import (
    ALIGNMENT_STATUS_VALID,
    log_runtime_warning,
)
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE
from storage.path_registry import resolve_canonical

_REQUIRED_COGNITION_FIELDS = (
    "persistence_score",
    "structural_rank",
    "synthesis_state",
    "location_bias",
)


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


def _load_latest_runtime_cognition() -> dict | None:
    """Load latest valid evaluation row from canonical cognition parquet.

    Parent STATE["runtime_cognition"] is intentionally ignored.
    """

    # Canonical path only — never fall back to legacy/repo-root copies.
    path = resolve_canonical("runtime_cognition_memory.parquet")
    if not os.path.exists(path):
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None

    if frame is None or len(frame) == 0 or "timestamp" not in frame.columns:
        return None

    work = frame.copy()
    work["_eval_ts"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.dropna(subset=["_eval_ts"])
    if len(work) == 0:
        return None

    for field in _REQUIRED_COGNITION_FIELDS:
        if field not in work.columns:
            return None

    tip = work["_eval_ts"].max()
    latest_rows = work.loc[work["_eval_ts"] == tip].copy()
    if len(latest_rows) == 0:
        return None

    identity_cols = list(_REQUIRED_COGNITION_FIELDS)
    if latest_rows[identity_cols].drop_duplicates().shape[0] > 1:
        return None

    latest_rows = latest_rows.sort_values("_eval_ts")
    row = latest_rows.iloc[-1]
    for field in _REQUIRED_COGNITION_FIELDS:
        if pd.isna(row[field]):
            return None

    alignment_status = "MISSING"
    if "alignment_status" in latest_rows.columns and pd.notna(row.get("alignment_status")):
        alignment_status = str(row["alignment_status"])

    alignment_score = None
    if "alignment_score" in latest_rows.columns and pd.notna(row.get("alignment_score")):
        alignment_score = float(row["alignment_score"])

    lineage_event_timestamp = None
    if (
        "lineage_event_timestamp" in latest_rows.columns
        and pd.notna(row.get("lineage_event_timestamp"))
    ):
        lineage_event_timestamp = pd.to_datetime(
            row["lineage_event_timestamp"],
            utc=True,
        )

    auction_event_timestamp = None
    if (
        "auction_event_timestamp" in latest_rows.columns
        and pd.notna(row.get("auction_event_timestamp"))
    ):
        auction_event_timestamp = pd.to_datetime(
            row["auction_event_timestamp"],
            utc=True,
        )

    return {
        "timestamp": tip,
        "persistence_score": float(row["persistence_score"]),
        "structural_rank": row["structural_rank"],
        "synthesis_state": row["synthesis_state"],
        "location_bias": row["location_bias"],
        "alignment_status": alignment_status,
        "alignment_score": alignment_score,
        "lineage_event_timestamp": lineage_event_timestamp,
        "auction_event_timestamp": auction_event_timestamp,
        "auction_state": (
            row["auction_state"]
            if "auction_state" in latest_rows.columns and pd.notna(row.get("auction_state"))
            else None
        ),
    }


def run():

    print()

    print(
        "PROBABILISTIC AUCTION ENGINE"
    )
    
    print()

    runtime_cognition = _load_latest_runtime_cognition()
    if runtime_cognition is None:
        print("RUNTIME COGNITION UNAVAILABLE")
        print("SKIP — missing required runtime cognition evaluation")
        print()
        return

    reinforcement = safe_read_parquet(
        "auction_reinforcement_memory.parquet"
    )
    if reinforcement is None or len(reinforcement) == 0:
        print("AUCTION REINFORCEMENT UNAVAILABLE")
        print("SKIP — missing required auction reinforcement memory")
        print()
        return

    STATE["auction_reinforcement"] = reinforcement

    latest = reinforcement.iloc[-1]

    evaluation_timestamp = runtime_cognition["timestamp"]
    if "timestamp" in reinforcement.columns:
        reinf_ts = pd.to_datetime(reinforcement["timestamp"], utc=True)
        if (reinf_ts == evaluation_timestamp).any():
            evaluation_timestamp = pd.to_datetime(
                reinforcement.loc[
                    reinf_ts == evaluation_timestamp, "timestamp"
                ].iloc[-1],
                utc=True,
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

    calibration_settings = get_calibration_settings()
    discipline_result = apply_probabilistic_discipline(
        raw_conviction=raw_conviction,
        diagnostics=diagnostic_exports,
        current_snapshot=current_snapshot,
        runtime_cognition=runtime_cognition,
        probabilistic_history=probabilistic_history,
        settings=calibration_settings,
    )

    diagnostic_exports["calibrated_conviction"] = discipline_result[
        "calibrated_conviction"
    ]

    runtime_conviction = resolve_runtime_conviction(
        raw_conviction,
        discipline_result,
        calibration_settings,
    )

    robustness_snapshot = {
        **current_snapshot,
        **diagnostic_exports,
        **discipline_result,
    }

    candle_history = STATE.get("candle_structure")
    regime_exports = infer_regime_segmentation(
        robustness_snapshot,
        runtime_cognition,
        probabilistic_history=probabilistic_history,
        candle_history=candle_history,
    )
    robustness_snapshot.update(regime_exports)

    drift_exports = compute_calibration_drift(
        probabilistic_history,
        robustness_snapshot,
    )
    log_drift_warning(drift_exports)

    stability_exports = compute_runtime_stability_exports(
        probabilistic_history,
        robustness_snapshot,
        runtime_cognition,
    )
    robustness_exports = {
        **regime_exports,
        **drift_exports,
        **stability_exports,
    }

    robustness_snapshot.update(robustness_exports)
    adversarial_exports = build_adversarial_exports(
        robustness_snapshot,
        history=probabilistic_history,
    )

    stabilization_exports = build_ontology_stabilization_exports(
        robustness_snapshot,
        runtime_cognition=runtime_cognition,
        probabilistic_history=probabilistic_history,
        reinforcement_history=reinforcement,
        candle_history=candle_history,
    )

    print(
        "AUCTION REGIME:"
    )

    print(
        auction_regime
    )

    print()
    print("REGIME STATE:")
    print(regime_exports.get("regime_state"))
    print("REGIME CONFIDENCE:")
    print(round(float(regime_exports.get("regime_confidence", 0.0)), 2))

    if adversarial_exports.get("adversarial_diagnostics_active"):
        print()
        print("FAILURE MODE:")
        print(adversarial_exports.get("failure_mode"))
        print("FRAGILITY SCORE:")
        print(round(float(adversarial_exports.get("probabilistic_fragility_score", 0.0)), 2))

    if stabilization_exports.get("ontology_stabilization_active"):
        print()
        print("ONTOLOGY STABILITY:")
        print(round(float(stabilization_exports.get("ontology_stability_score", 0.0)), 2))
        print("SEMANTIC FRAGILITY:")
        print(round(float(stabilization_exports.get("semantic_fragility_score", 0.0)), 2))

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
            runtime_conviction,
            2
        )
    )

    if calibration_settings.use_disciplined_conviction_at_runtime:
        print()
        print("RAW CONVICTION (diagnostic):")
        print(round(raw_conviction, 2))
        print("DISCIPLINED CONVICTION:")
        print(round(discipline_result["disciplined_conviction"], 2))

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

    conviction_probability = min(runtime_conviction, 1.0)

    if len(probabilistic_history) > 0 and "timestamp" in probabilistic_history.columns:
        existing_ts = pd.to_datetime(probabilistic_history["timestamp"], utc=True)
        if (existing_ts == evaluation_timestamp).any():
            print()
            print("SKIP — probabilistic evaluation already exists for cognition tip")
            print(evaluation_timestamp)
            print()
            return

    row_payload = {

    "timestamp":
        evaluation_timestamp,

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

    **discipline_result,

    **robustness_exports,

    **adversarial_exports,

    **stabilization_exports,

    }

    if runtime_cognition.get("auction_event_timestamp") is not None:
        row_payload["auction_event_timestamp"] = runtime_cognition[
            "auction_event_timestamp"
        ]

    row = pd.DataFrame([row_payload])

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

    if runtime_cognition.get("lineage_event_timestamp") is not None:
        row["lineage_event_timestamp"] = runtime_cognition[
            "lineage_event_timestamp"
        ]

    state_payload = {

        "timestamp":
            evaluation_timestamp,

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
            key: stabilization_exports.get(
                key,
                adversarial_exports.get(
                    key,
                    robustness_exports.get(
                        key,
                        discipline_result.get(
                            key,
                            diagnostic_exports.get(key),
                        ),
                    ),
                ),
            )
            for key in (
                list(DIAGNOSTIC_EXPORT_COLUMNS)
                + list(DISCIPLINE_EXPORT_COLUMNS)
                + list(regime_exports.keys())
                + list(drift_exports.keys())
                + list(stability_exports.keys())
                + list(ADVERSARIAL_EXPORT_COLUMNS)
                + list(STABILIZATION_EXPORT_COLUMNS)
            )
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
