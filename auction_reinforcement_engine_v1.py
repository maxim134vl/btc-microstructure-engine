import math
import os

import numpy as np
import pandas as pd

from runtime_integrity import (
    ALIGNMENT_STATUS_VALID,
    log_runtime_warning,
)
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE
from storage.path_registry import resolve_canonical, resolve_read, resolve_write

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
        return float(raw_alignment), alignment_status, float(raw_alignment) * 0.25

    log_runtime_warning(
        f"Reinforcement skipped alignment contribution "
        f"(status={alignment_status})"
    )
    return 0.0, alignment_status, 0.0


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
        # No source priority among duplicate evaluation identities.
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

    auction_state_lineage = None
    if "auction_state" in latest_rows.columns and pd.notna(row.get("auction_state")):
        auction_state_lineage = row["auction_state"]

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
        "auction_state_lineage": auction_state_lineage,
    }


def run():

    print()

    print(
        "AUCTION REINFORCEMENT ENGINE"
    )

    print()

    synthesis = STATE[
        "auction_synthesis"
    ]

    latest_synthesis = (
        synthesis.iloc[-1]
    )

    runtime_cognition = _load_latest_runtime_cognition()
    if runtime_cognition is None:
        print("RUNTIME COGNITION UNAVAILABLE")
        print("SKIP — missing required runtime cognition evaluation")
        print()
        return

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

    alignment_score, alignment_status, alignment_component = (
        _resolve_alignment(runtime_cognition)
    )

    location_bias = runtime_cognition.get(
        "location_bias",
        "NEUTRAL"

    )

    evaluation_timestamp = runtime_cognition["timestamp"]

    try:

        memory = pd.read_parquet(
            resolve_read("auction_reinforcement_memory.parquet")
        )

    except:

        memory = pd.DataFrame()

    if len(memory) > 0 and "timestamp" in memory.columns:
        existing_ts = pd.to_datetime(memory["timestamp"], utc=True)
        if (existing_ts == evaluation_timestamp).any():
            print("SKIP — reinforcement evaluation already exists for cognition tip")
            print(evaluation_timestamp)
            print()
            STATE["auction_reinforcement"] = memory
            return

    auction_state = latest_synthesis[
        "auction_state"
    ]

    volume_response = STATE[
        "volume_response"
    ]

    latest_response = (
        volume_response.iloc[-1]
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

    reinforcement_component = 0.5

    if effort_result_state == (
        "ABSORPTION_RESPONSE"
    ):

        reinforcement_component += 0.15

    unfinished_auction_component = 0.0

    if unfinished_auction == True:

        unfinished_auction_component = 0.1
        reinforcement_component += 0.1

    if localized_behavior == (
        "localized_distribution"
    ):

        reinforcement_component += 0.1

    if auction_state != (
        "NEUTRAL"
    ):

        reinforcement_component += 0.15

    persistence_component = persistence_score * 0.2
    reinforcement_component += persistence_component

    if structural_rank == "HIGH":

        reinforcement_component += 0.15

    if synthesis_state == (
        "LOCAL_EXHAUSTION"
    ):

        reinforcement_component -= 0.2

    belief_strength = reinforcement_component
    belief_strength += alignment_component

    location_component = 0.0

    if location_bias == (
        "LOWER_ABSORPTION"
    ):

        location_component += 0.20
        belief_strength += 0.20

    if location_bias == (
        "UPPER_DISTRIBUTION"
    ):

        location_component -= 0.15
        belief_strength -= 0.15

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        location_component -= 0.10
        belief_strength -= 0.10

    if location_bias == (
        "LOWER_CAPITULATION"
    ):

        location_component += 0.10
        belief_strength += 0.10

    from calibration_discipline import apply_reinforcement_discipline

    belief_strength, alignment_component, persistence_component, rein_discipline_exports = (
        apply_reinforcement_discipline(
            belief_strength,
            alignment_component,
            persistence_component,
            memory,
            runtime_cognition,
        )
    )

    conflict_score = 0

    if (
        alignment_score < 0.50
        and
        belief_strength > 0.75
    ):

        conflict_score += 0.20

    if (

        structural_rank == "LOW"

        and

        belief_strength > 0.65

    ):

        conflict_score += 0.10

    if location_bias == (
        "MID_AUCTION_TRANSFER"
    ):

        conflict_score += 0.10

    conflict_penalty = conflict_score
    belief_strength -= conflict_penalty

    entropy_penalty = _belief_entropy(memory.tail(25))

    belief_strength = (

        1 -

        np.exp(

            -belief_strength

        )

    )

    belief_strength = max(
        0,
        min(
            belief_strength,
            1
        )
    )

    belief_state = (
        "NEUTRAL_CONVICTION"
    )

    if belief_strength >= 0.8:

        belief_state = (
            "HIGH_CONVICTION"
        )

    elif belief_strength >= 0.65:

        belief_state = (
            "MODERATE_CONVICTION"
        )

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

    row_payload = {

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
            evaluation_timestamp,

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

        **rein_discipline_exports,

    }

    if runtime_cognition.get("auction_event_timestamp") is not None:
        row_payload["auction_event_timestamp"] = runtime_cognition[
            "auction_event_timestamp"
        ]

    row = pd.DataFrame([row_payload])

    row = apply_lineage_metadata(
        row,
        engine_name="auction_reinforcement_engine_v1.py",
        source_parquet="auction_synthesis_memory.parquet",
        dependency_chain=[
            "runtime_cognition_memory.parquet",
            "auction_synthesis_memory.parquet",
            "volume_response_state.parquet",
            "auction_reinforcement_engine_v1.py",
            "auction_reinforcement_memory.parquet",
        ],
        event_timestamp_col="timestamp",
    )

    # Preserve cognition MTF/event lineage; do not replace with evaluation tip.
    if runtime_cognition.get("lineage_event_timestamp") is not None:
        row["lineage_event_timestamp"] = runtime_cognition[
            "lineage_event_timestamp"
        ]

    memory = pd.concat([

        memory,
        row

    ])

    memory = memory.tail(100)

    memory.to_parquet(
        resolve_write("auction_reinforcement_memory.parquet")
    )

    STATE["auction_reinforcement"] = (
        memory
    )


if __name__ == "__main__":

    run()
