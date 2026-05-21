DEPENDENCIES = {

    "auction_synthesis_engine_v1.py": [
        "volume_response_state.parquet",
        "htf_structure_memory.parquet",
        "htf_ltf_context_memory.parquet"
    ],

    "probabilistic_auction_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "auction_reinforcement_memory.parquet"
    ],

    "state_transition_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "probabilistic_auction_memory.parquet"
    ],

    "auction_decay_engine_v1.py": [
        "auction_convergence_memory.parquet",
        "auction_reinforcement_memory.parquet"
    ]

}
