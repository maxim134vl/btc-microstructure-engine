DEPENDENCIES = {
    "volume_localization_engine_v2.py": ["candle_geometry_v2_memory.parquet"],
    'candle_geometry_engine_v2.py': ['live_market_feed.parquet'],
    'behavioral_sequence_memory_v1.py': ['temporal_context_memory.parquet', 'volume_localization_v2_memory.parquet', 'volume_reactions.parquet', 'behavioral_events_memory.parquet'],
    'behavioral_volume_observer_v1.py': ['contextual_memory_state.parquet', 'temporal_context_memory.parquet', 'volume_localization_v2_memory.parquet', 'volume_reactions.parquet', 'behavioral_events_memory.parquet', 'behavioral_sequence_memory.parquet', 'adaptive_behavioral_weights.parquet'],
    'microstructure_candle_engine_v1.py': ['live_market_feed.parquet'],
    'volume_response_engine_v1.py': ['volume_classification_memory.parquet', 'candle_structure_memory.parquet', 'candle_geometry_v2_memory.parquet', 'volume_localization_v2_memory.parquet', 'volume_reactions.parquet'],
    'climactic_behavior_engine_v1.py': ['volume_response_state.parquet'],
    'auction_convergence_engine_v1.py': ['volume_response_state.parquet'],
    'adaptive_meta_cognition_engine_v1.py': ['probabilistic_auction_memory.parquet', 'auction_reinforcement_memory.parquet'],


    # Stage 2B1.1B candidate producers (source-true reads).
    "live_volume_flow_engine_v1.py": [
        "live_market_feed.parquet",
    ],

    "liquidity_cluster_engine_v1.py": [
        "volume_localization_memory.parquet",
    ],

    "flow_liquidity_interaction_engine_v3.py": [
        "live_volume_flow_memory.parquet",
        "live_market_feed.parquet",
        "liquidity_clusters_memory.parquet",
    ],

    "htf_structure_engine_v1.py": [
        "live_market_feed.parquet",
    ],

    "htf_ltf_context_engine_v1.py": [
        "live_volume_flow_memory.parquet",
        "flow_liquidity_interaction_memory.parquet",
        "htf_structure_memory.parquet",
    ],

    "auction_synthesis_engine_v1.py": [
        "volume_response_state.parquet",
        "auction_convergence_memory.parquet",
        "htf_structure_memory.parquet",
        "htf_ltf_context_memory.parquet"
    ],

    "stage2_cognition_runtime_v1.py": [
        "candle_structure_memory.parquet",
        "auction_synthesis_memory.parquet",
    ],

    "runtime_cognition_engine_v1.py": [
        "runtime_cognition_memory.parquet",
        "multi_timeframe_synthesis.parquet",
    ],

    "intermediate_cognition_engine_v1.py": [
        "candle_structure_memory.parquet",
        "runtime_cognition_memory.parquet",
    ],

    "auction_reinforcement_engine_v1.py": [
        "runtime_cognition_memory.parquet",
        "auction_synthesis_memory.parquet",
        "volume_response_state.parquet",
    ],

    "probabilistic_auction_engine_v1.py": [
        "runtime_cognition_memory.parquet",
        "auction_reinforcement_memory.parquet",
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
