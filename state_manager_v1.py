import os
import pandas as pd

# =====================================
# STATE REGISTRY
# =====================================

STATE = {}

# =====================================
# LOADERS
# =====================================

STATE["auction_synthesis"] = pd.read_parquet(
    "auction_synthesis_memory.parquet"
)

try:

    STATE["auction_reinforcement"] = pd.read_parquet(
        "auction_reinforcement_memory.parquet"
    )

except Exception:

    STATE["auction_reinforcement"] = pd.DataFrame()

STATE["auction_convergence"] = pd.read_parquet(
    "auction_convergence_memory.parquet"
)

STATE["volume_response"] = pd.read_parquet(
    "volume_response_state.parquet"
)

STATE["behavioral_sequence"] = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

STATE["probabilistic_auction"] = pd.read_parquet(
    "probabilistic_auction_memory.parquet"
)

STATE["adaptive_meta_cognition"] = pd.read_parquet(
    "adaptive_meta_cognition_state.parquet"
)

def refresh_state():

    global STATE

    STATE["candle_structure"] = (
        pd.read_parquet(
            "candle_structure_memory.parquet"
        )
    )

    STATE["auction_synthesis"] = (
        pd.read_parquet(
            "auction_synthesis_memory.parquet"
        )
    )

    STATE["auction_convergence"] = (
        pd.read_parquet(
            "auction_convergence_memory.parquet"
        )
    )

    STATE["auction_reinforcement"] = (

        pd.read_parquet(
            "auction_reinforcement_memory.parquet"
        )

        if os.path.exists(
            "auction_reinforcement_memory.parquet"
        )

        else pd.DataFrame()

    )

    STATE["probabilistic_auction"] = (
        pd.read_parquet(
            "probabilistic_auction_memory.parquet"
        )
    )

    STATE["adaptive_meta_cognition"] = (
        pd.read_parquet(
            "adaptive_meta_cognition_state.parquet"
        )
    )

refresh_state()
