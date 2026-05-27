import pandas as pd

from parquet_utils import safe_read_parquet
from runtime_integrity import (
    ALIGNMENT_STATUS_INVALID,
    ALIGNMENT_STATUS_MISSING,
    ALIGNMENT_STATUS_STALE,
    ALIGNMENT_STATUS_VALID,
    compute_drift_metrics,
    enrich_alignment_status,
    export_alignment_audit,
    log_runtime_error,
    log_runtime_warning,
)
from runtime_lineage import lineage_record_from_row
from state_manager_v1 import STATE

RUNTIME_COGNITION_MEMORY_PATH = "runtime_cognition_memory.parquet"
SYNTHESIS_PATH = "multi_timeframe_synthesis.parquet"


def resolve_alignment_for_state(latest_state: pd.Series) -> dict:
    status = latest_state.get("alignment_status", ALIGNMENT_STATUS_MISSING)
    alignment_score = latest_state.get("alignment_score")

    if status == ALIGNMENT_STATUS_VALID:
        return {
            "alignment_status": status,
            "alignment_score": float(alignment_score),
        }

    if status == ALIGNMENT_STATUS_STALE:
        log_runtime_warning(
            "Stale alignment_score for cognition timestamp "
            f"{latest_state.get('timestamp')}"
        )
        if pd.notna(alignment_score):
            return {
                "alignment_status": status,
                "alignment_score": float(alignment_score),
            }

    if status == ALIGNMENT_STATUS_MISSING:
        log_runtime_warning(
            "Missing alignment_score for cognition timestamp "
            f"{latest_state.get('timestamp')}"
        )

    if status == ALIGNMENT_STATUS_INVALID:
        log_runtime_error(
            "Invalid alignment_score for cognition timestamp "
            f"{latest_state.get('timestamp')}: {alignment_score!r}"
        )

    return {
        "alignment_status": status,
        "alignment_score": None,
    }


def run():

    print()
    print(
        "RUNTIME COGNITION ENGINE"
    )
    print()

    cognition = safe_read_parquet(
        RUNTIME_COGNITION_MEMORY_PATH
    )

    synthesis = safe_read_parquet(
        SYNTHESIS_PATH
    )

    cognition = enrich_alignment_status(
        cognition,
        synthesis=synthesis if len(synthesis) > 0 else None,
    )

    audit = export_alignment_audit(cognition)
    if len(audit) > 0:
        log_runtime_warning(
            f"Exported {len(audit)} invalid/missing/stale alignment rows "
            "to runtime_cognition_alignment_audit.parquet"
        )

    if len(cognition) == 0:

        print(
            "NO COGNITION STATES"
        )

        print()

        return

    latest_state = cognition.iloc[-1]
    alignment_payload = resolve_alignment_for_state(latest_state)
    lineage = lineage_record_from_row(latest_state)

    STATE["runtime_cognition"] = {

        "timestamp":
            latest_state["timestamp"],

        "synthesis_state":
            latest_state["synthesis_state"],

        "trigger_event":
            latest_state["trigger_event"],

        "persistence":
            latest_state["persistence"],

        "persistence_score":
            latest_state["persistence_score"],

        "structural_rank":
            latest_state["structural_rank"],

        "alignment_score":
            alignment_payload["alignment_score"],

        "alignment_status":
            alignment_payload["alignment_status"],

        "location_bias":
            latest_state["location_bias"],

        "lineage_engine":
            lineage.get("lineage_engine"),

        "lineage_source_parquet":
            lineage.get("lineage_source_parquet"),

        "lineage_event_timestamp":
            lineage.get("lineage_event_timestamp"),

        "lineage_propagation_timestamp":
            lineage.get("lineage_propagation_timestamp"),

        "lineage_dependency_chain":
            lineage.get("lineage_dependency_chain"),

    }

    metrics, drift_warnings = compute_drift_metrics()
    for warning in drift_warnings:
        log_runtime_warning(warning)

    print(
        "ALIGNMENT STATUS:",
        alignment_payload["alignment_status"],
    )

    print(
        "DRIFT METRICS:",
        metrics,
    )

    print(
        STATE["runtime_cognition"]
    )

    print()

# =====================================
# START
# =====================================

if __name__ == "__main__":

    run()
