import os
import pandas as pd

from parquet_utils import safe_read_parquet

# =====================================
# STATE REGISTRY
# =====================================

STATE = {}

_STATE_KEYS = {
    "auction_synthesis": "auction_synthesis_memory.parquet",
    "auction_reinforcement": "auction_reinforcement_memory.parquet",
    "auction_convergence": "auction_convergence_memory.parquet",
    "volume_response": "volume_response_state.parquet",
    "behavioral_sequence": "behavioral_sequence_memory.parquet",
    "probabilistic_auction": "probabilistic_auction_memory.parquet",
    "adaptive_meta_cognition": "adaptive_meta_cognition_state.parquet",
    "candle_structure": "candle_structure_memory.parquet",
}


def _load_state_key(key: str) -> pd.DataFrame:
    return safe_read_parquet(_STATE_KEYS[key])


# =====================================
# LOADERS
# =====================================

STATE["auction_synthesis"] = _load_state_key("auction_synthesis")

try:
    STATE["auction_reinforcement"] = _load_state_key("auction_reinforcement")
except Exception:
    STATE["auction_reinforcement"] = pd.DataFrame()

STATE["auction_convergence"] = _load_state_key("auction_convergence")

STATE["volume_response"] = _load_state_key("volume_response")

STATE["behavioral_sequence"] = _load_state_key("behavioral_sequence")

STATE["probabilistic_auction"] = _load_state_key("probabilistic_auction")

STATE["adaptive_meta_cognition"] = _load_state_key("adaptive_meta_cognition")


def refresh_state():

    global STATE

    for key in _STATE_KEYS:
        if key == "auction_reinforcement":
            path_key = _STATE_KEYS[key]
            from storage.path_registry import resolve_read

            if os.path.exists(resolve_read(path_key)):
                STATE[key] = safe_read_parquet(path_key)
            else:
                STATE[key] = pd.DataFrame()
        else:
            STATE[key] = _load_state_key(key)


refresh_state()
