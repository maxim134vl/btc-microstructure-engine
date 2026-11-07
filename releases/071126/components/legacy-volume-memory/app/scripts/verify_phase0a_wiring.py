"""Phase 0A runtime wiring verification (non-destructive)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from live_feed_paths import (
    CANONICAL_LIVE_FEED_PATH,
    LEGACY_LIVE_FEED_PATH,
)
from runtime_config import (
    LEGACY_LIVE_FEED_PARQUET,
    LIVE_MARKET_FEED_PARQUET,
)
from stage2_cognition_runtime_v1 import (
    RUNTIME_COGNITION_MEMORY_PATH,
    SYNTHESIS_OUTPUT_PATH,
    run as run_stage2,
)
from runtime_cognition_engine_v1 import run as run_runtime_cognition
from state_manager_v1 import STATE, refresh_state


def check_paths() -> bool:
    ok = True

    if LIVE_MARKET_FEED_PARQUET != CANONICAL_LIVE_FEED_PATH:
        print("FAIL: runtime_config canonical path mismatch")
        ok = False
    else:
        print("PASS: canonical feed path constant")

    if LEGACY_LIVE_FEED_PARQUET != LEGACY_LIVE_FEED_PATH:
        print("FAIL: runtime_config legacy path mismatch")
        ok = False
    else:
        print("PASS: legacy feed mirror path constant")

    return ok


def check_stage2_outputs() -> bool:
    before_cognition_mtime = None
    if os.path.exists(RUNTIME_COGNITION_MEMORY_PATH):
        before_cognition_mtime = os.path.getmtime(
            RUNTIME_COGNITION_MEMORY_PATH
        )

    run_stage2()

    if not os.path.exists(SYNTHESIS_OUTPUT_PATH):
        print("FAIL: multi_timeframe_synthesis.parquet not written")
        return False

    if not os.path.exists(RUNTIME_COGNITION_MEMORY_PATH):
        print("FAIL: runtime_cognition_memory.parquet not written")
        return False

    synthesis = pd.read_parquet(SYNTHESIS_OUTPUT_PATH)
    cognition = pd.read_parquet(RUNTIME_COGNITION_MEMORY_PATH)

    if len(cognition) == 0:
        print("WARN: cognition memory empty (no synthesis events)")
    else:
        print(
            "PASS: cognition rows =",
            len(cognition),
            "latest =",
            cognition.iloc[-1]["timestamp"],
        )

    after_cognition_mtime = os.path.getmtime(
        RUNTIME_COGNITION_MEMORY_PATH
    )

    if (
        before_cognition_mtime is not None
        and after_cognition_mtime == before_cognition_mtime
    ):
        print(
            "WARN: runtime_cognition_memory mtime unchanged "
            "(dependency guard may skip in loop)"
        )
    else:
        print("PASS: runtime_cognition_memory updated")

    required_cols = {
        "timestamp",
        "synthesis_state",
        "trigger_event",
        "persistence",
        "persistence_score",
        "structural_rank",
        "alignment_score",
        "location_bias",
    }

    missing = required_cols - set(cognition.columns)
    if missing:
        print("FAIL: cognition missing columns:", sorted(missing))
        return False

    print("PASS: cognition schema columns present")
    print("PASS: synthesis rows =", len(synthesis))
    return True


def check_runtime_cognition_state() -> bool:
    run_runtime_cognition()
    refresh_state()

    if "runtime_cognition" not in STATE:
        print("FAIL: STATE runtime_cognition not populated")
        return False

    cognition = STATE["runtime_cognition"]
    if not cognition.get("timestamp"):
        print("FAIL: latest cognition timestamp missing")
        return False

    print(
        "PASS: STATE runtime_cognition loaded:",
        cognition.get("synthesis_state"),
        "@",
        cognition.get("timestamp"),
    )
    return True


def check_climax_uses_dataset() -> bool:
    from auction_climax_engine_v1 import process_auction_climax
    from multi_timeframe_dataset_builder import aggregate_behavioral_timeframe

    refresh_state()
    full = STATE["candle_structure"].copy()

    m30_dataset = aggregate_behavioral_timeframe(
        full.copy(),
        "M30",
    )

    m30_result = process_auction_climax(
        m30_dataset,
        "M30",
    )

    m30_states = m30_result["auction_states"]

    if len(m30_states) == 0:
        print("WARN: no m30 climax events to validate dataset binding")
        return True

    allowed = set(m30_dataset["timestamp"])
    outside = m30_states[
        ~m30_states["timestamp"].isin(allowed)
    ]

    if len(outside) > 0:
        print("FAIL: climax produced timestamps outside passed dataset")
        return False

    print("PASS: climax uses passed dataset argument")
    return True


def main() -> int:
    print()
    print("PHASE 0A RUNTIME WIRING VERIFICATION")
    print("=" * 60)

    checks = [
        check_paths(),
        check_climax_uses_dataset(),
        check_stage2_outputs(),
        check_runtime_cognition_state(),
    ]

    print()
    if all(checks):
        print("RESULT: PASS")
        return 0

    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
