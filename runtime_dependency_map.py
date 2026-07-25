DEPENDENCIES = {

    "auction_synthesis_engine_v1.py": [
        "volume_response_state.parquet",
        "htf_structure_memory.parquet",
        "htf_ltf_context_memory.parquet"
    ],

    "stage2_cognition_runtime_v1.py": [
        "candle_structure_memory.parquet"
    ],

    "runtime_cognition_engine_v1.py": [
        "runtime_cognition_memory.parquet"
    ],

    "intermediate_cognition_engine_v1.py": [
        "candle_structure_memory.parquet",
        "runtime_cognition_memory.parquet",
    ],

    "probabilistic_auction_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "auction_reinforcement_memory.parquet"
    ],

    "auction_context_arbitration_engine_v1.py": [
        "candle_structure_memory.parquet",
        "volume_response_state.parquet",
        "auction_convergence_memory.parquet",
    ],

    "state_transition_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "probabilistic_auction_memory.parquet"
    ],

    "auction_decay_engine_v1.py": [
        "auction_convergence_memory.parquet",
        "auction_reinforcement_memory.parquet"
    ],

    "mtf_availability_runtime_engine_v1.py": [
        "candle_structure_memory.parquet"
    ],

}
