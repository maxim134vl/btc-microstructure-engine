"""Phase 0B runtime integrity verification (non-destructive)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from parquet_utils import safe_read_parquet
from runtime_integrity import (
    ALIGNMENT_STATUS_VALID,
    enrich_alignment_status,
)
from runtime_lineage import LINEAGE_COLUMNS
from runtime_cognition_engine_v1 import run as run_runtime_cognition
from stage2_cognition_runtime_v1 import (
    RUNTIME_COGNITION_MEMORY_PATH,
    SYNTHESIS_OUTPUT_PATH,
    run as run_stage2,
)
from state_manager_v1 import STATE, refresh_state

DECOMPOSITION_COLUMNS = [
    "alignment_component",
    "persistence_component",
    "location_component",
    "unfinished_auction_component",
    "entropy_penalty",
    "conflict_penalty",
    "reinforcement_component",
]

TARGET_PARQUETS = [
    RUNTIME_COGNITION_MEMORY_PATH,
    SYNTHESIS_OUTPUT_PATH,
    "auction_reinforcement_memory.parquet",
    "probabilistic_auction_memory.parquet",
]


def check_lineage_columns() -> bool:
    ok = True

    for path in TARGET_PARQUETS:
        if not os.path.exists(path):
            print(f"WARN: {path} missing — run stage2/runtime loop first")
            ok = False
            continue

        frame = safe_read_parquet(path)
        if len(frame) == 0:
            print(f"WARN: {path} empty")
            continue

        missing = set(LINEAGE_COLUMNS) - set(frame.columns)
        if missing:
            print(f"FAIL: {path} missing lineage columns:", sorted(missing))
            ok = False
            continue

        latest = frame.iloc[-1]
        if not latest.get("lineage_engine"):
            print(f"FAIL: {path} missing lineage_engine on latest row")
            ok = False
            continue

        print(
            f"PASS: {path} lineage present "
            f"(engine={latest.get('lineage_engine')})"
        )

    return ok


def check_alignment_integrity() -> bool:
    if not os.path.exists(RUNTIME_COGNITION_MEMORY_PATH):
        print("FAIL: runtime cognition parquet missing")
        return False

    cognition = safe_read_parquet(RUNTIME_COGNITION_MEMORY_PATH)
    synthesis = safe_read_parquet(SYNTHESIS_OUTPUT_PATH)

    enriched = enrich_alignment_status(
        cognition,
        synthesis=synthesis,
    )

    if "alignment_status" not in enriched.columns:
        print("FAIL: alignment_status not derived")
        return False

    latest = enriched.iloc[-1]
    run_runtime_cognition()
    refresh_state()

    state = STATE.get("runtime_cognition", {})
    if "alignment_status" not in state:
        print("FAIL: STATE missing alignment_status")
        return False

    if state["alignment_status"] != latest["alignment_status"]:
        print("FAIL: STATE alignment_status mismatch with enriched cognition")
        return False

    if state["alignment_status"] == ALIGNMENT_STATUS_VALID:
        if state.get("alignment_score") is None:
            print("FAIL: VALID alignment missing score in STATE")
            return False
    elif state.get("alignment_score") not in (None, float("nan")):
        if pd.notna(state.get("alignment_score")):
            print(
                "FAIL: non-VALID alignment_status still has numeric "
                "alignment_score in STATE"
            )
            return False

    invalid_defaults = enriched[
        enriched["alignment_status"].isin(["MISSING", "INVALID", "STALE"])
        & enriched["alignment_score"].notna()
        & (enriched["alignment_score"].astype(float) == 0.25)
    ]
    if len(invalid_defaults) > 0:
        print("FAIL: fake 0.25 alignment injected for invalid rows")
        return False

    print(
        "PASS: alignment integrity — status="
        f"{state['alignment_status']}, score={state.get('alignment_score')}"
    )
    return True


def check_timestamp_propagation() -> bool:
    run_runtime_cognition()
    refresh_state()

    drift_metrics = STATE.get("runtime_cognition", {}).get("drift_metrics")
    if not drift_metrics:
        print("FAIL: drift_metrics not attached to runtime cognition STATE")
        return False

    required_keys = {
        "checked_at",
        "stale_threshold_seconds",
        "cognition_rows",
        "synthesis_rows",
    }
    missing = required_keys - set(drift_metrics.keys())
    if missing:
        print("FAIL: drift_metrics missing keys:", sorted(missing))
        return False

    print(
        "PASS: timestamp drift metrics present "
        f"(warnings={drift_metrics.get('warning_count', 0)})"
    )
    return True


def check_conviction_decomposition() -> bool:
    ok = True

    for path in [
        "auction_reinforcement_memory.parquet",
        "probabilistic_auction_memory.parquet",
    ]:
        if not os.path.exists(path):
            print(f"WARN: {path} missing — decomposition not yet exported")
            ok = False
            continue

        frame = safe_read_parquet(path)
        if len(frame) == 0:
            print(f"WARN: {path} empty")
            continue

        missing = set(DECOMPOSITION_COLUMNS) - set(frame.columns)
        if missing:
            print(f"FAIL: {path} missing decomposition columns:", sorted(missing))
            ok = False
            continue

        latest = frame.iloc[-1]
        print(
            f"PASS: {path} decomposition exported "
            f"(reinforcement_component={latest.get('reinforcement_component')})"
        )

    return ok


def check_no_stale_cognition_injection() -> bool:
    run_runtime_cognition()
    refresh_state()

    cognition = safe_read_parquet(RUNTIME_COGNITION_MEMORY_PATH)
    synthesis = safe_read_parquet(SYNTHESIS_OUTPUT_PATH)
    enriched = enrich_alignment_status(cognition, synthesis=synthesis)

    latest = enriched.iloc[-1]
    state = STATE["runtime_cognition"]

    if latest["alignment_status"] != ALIGNMENT_STATUS_VALID:
        if pd.notna(state.get("alignment_score")):
            print(
                "FAIL: stale/missing alignment injected into STATE as numeric score"
            )
            return False

    if state.get("lineage_engine") != latest.get("lineage_engine"):
        print("FAIL: STATE lineage_engine diverges from latest cognition row")
        return False

    print("PASS: no stale cognition injection into STATE")
    return True


def bootstrap_runtime_chain() -> None:
    run_stage2()
    run_runtime_cognition()
    refresh_state()

    from auction_reinforcement_engine_v1 import run as run_reinforcement
    from probabilistic_auction_engine_v1 import run as run_probabilistic

    run_reinforcement()
    run_probabilistic()
    refresh_state()


def main() -> int:
    print()
    print("PHASE 0B RUNTIME INTEGRITY VERIFICATION")
    print("=" * 60)

    bootstrap_runtime_chain()

    checks = [
        ("lineage columns", check_lineage_columns()),
        ("alignment integrity", check_alignment_integrity()),
        ("timestamp propagation", check_timestamp_propagation()),
        ("conviction decomposition", check_conviction_decomposition()),
        ("no stale cognition injection", check_no_stale_cognition_injection()),
    ]

    print()
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print()
    if all(result for _, result in checks):
        print("RESULT: PASS")
        return 0

    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
