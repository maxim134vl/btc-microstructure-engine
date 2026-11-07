import sys

import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row,
)
from runtime_cache import load_parquet_cached

MEMORY_FILE = "state_transition_memory.parquet"
STATE_FILE = "state_transition_engine_state.parquet"


def _dependency_signature(recent_synthesis, recent_probabilistic) -> str:
    return str(recent_synthesis.iloc[-1]["auction_state"]) + str(
        recent_probabilistic.iloc[-1]["auction_regime"]
    )


def run() -> int:
    """Run state transition engine. Returns 0 on success or clean deferral."""

    print()
    print("STATE TRANSITION ENGINE")

    synthesis = load_parquet_cached("auction_synthesis_memory.parquet")
    probabilistic = load_parquet_cached("probabilistic_auction_memory.parquet")

    recent_synthesis = synthesis.tail(2)
    recent_probabilistic = probabilistic.tail(2)

    if len(recent_synthesis) < 2:
        print()
        print("WAITING FOR SECOND STATE")
        print("(deferred — pipeline continues)")
        return 0

    if len(recent_probabilistic) < 2:
        print()
        print("WAITING FOR SECOND REGIME")
        print("(deferred — pipeline continues)")
        return 0

    current_dependency_state = _dependency_signature(
        recent_synthesis,
        recent_probabilistic,
    )

    try:
        previous_state_df = safe_read_parquet(STATE_FILE)
        if len(previous_state_df) > 0:
            previous_dependency_state = previous_state_df.iloc[-1]["dependency_state"]
            if previous_dependency_state == current_dependency_state:
                print()
                print("NO UPSTREAM STATE CHANGE")
                return 0
    except Exception:
        pass

    previous_state = recent_synthesis.iloc[-2]["auction_state"]
    current_state = recent_synthesis.iloc[-1]["auction_state"]
    previous_regime = recent_probabilistic.iloc[-2]["auction_regime"]
    current_regime = recent_probabilistic.iloc[-1]["auction_regime"]

    transition_state = "STABLE_STATE"

    if previous_state != current_state:
        transition_state = "AUCTION_STATE_TRANSITION"

    if previous_regime != current_regime:
        transition_state = "REGIME_TRANSITION"

    if previous_state != current_state and previous_regime != current_regime:
        transition_state = "FULL_COGNITIVE_TRANSITION"

    print()
    print("PREVIOUS STATE:")
    print(previous_state)
    print()
    print("CURRENT STATE:")
    print(current_state)
    print()
    print("PREVIOUS REGIME:")
    print(previous_regime)
    print()
    print("CURRENT REGIME:")
    print(current_regime)
    print()
    print("TRANSITION STATE:")
    print(transition_state)

    new_row = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp.now().tz_localize(None),
                "previous_state": previous_state,
                "current_state": current_state,
                "previous_regime": previous_regime,
                "current_regime": current_regime,
                "transition_state": transition_state,
            }
        ]
    )

    append_state_row(MEMORY_FILE, new_row)

    print()
    print("MEMORY SAVED:")
    print(MEMORY_FILE)

    dependency_state = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp.now().tz_localize(None),
                "dependency_state": current_dependency_state,
            }
        ]
    )

    append_state_row(STATE_FILE, dependency_state, max_rows=1)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(run())
