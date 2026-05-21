# ACTIVE

./collectors/oi_collector.py
./collectors/orderbook_collector.py
./collectors/multi_exchange_collector.py
./collectors/liquidation_collector.py

./engines/acceptance_engine.py
./engines/divergence_aftermath_engine.py
./engines/volume_outcome_engine.py
./engines/regime_engine.py
./engines/volume_cluster_engine.py
./engines/transition_labeling_engine.py
./engines/inventory_engine.py
./engines/market_narrative_engine.py
./engines/volume_classification_engine.py
./engines/narrative_validation_engine.py
./engines/volume_normalizer.py
./engines/signal_registry_engine.py
./engines/regime_signal_registry.py
./engines/structure_engine.py
./engines/liquidity_vacuum_engine.py
./engines/volume_memory_engine.py
./engines/divergence_engine.py
./engines/volume_reaction_engine.py

./runtime/realtime_streaming_engine_v1.py
./runtime/run_canonical_pipeline.py
./runtime/live_engine_runner.py

./master_auction_runtime_v1.py
./behavioral_runtime_loop_v1.py
./behavioral_runtime_orchestrator_v1.py

./canonical_schema_registry.py
./schema_validation_engine_v1.py
./engine_registry.py
./state_engine.py
./regime_detector.py
./market_context_engine_v1.py
./market_pressure_engine.py
./volume_engine.py
./market_memory.py
./event_logger.py
./event_analytics.py

# EXPERIMENTAL

# LEGACY

./archive/*
./legacy/*
./archive/mutation_legacy/*
./archive/legacy_cognition/*
./archive/reinforcement_legacy/*
./archive/predictive_legacy/*

# RISKS

1. Очень много fragmented engines v1/v2/v3/v4/v5/v6/v7/v8/v9

initiative_memory_engine_v1-v9
flow_liquidity_interaction_engine_v1-v3
autonomous_runtime_v1-v2
temporal_decay_engine_v1-v2
clean_stopping_test_v1-v3
behavioral_replay_m15_v1-v3

2. Огромное количество standalone research scripts

Это создаст:
- dependency chaos
- migration ambiguity
- unclear ownership

3. Replay layer размазан по research/replay/

Нет unified replay architecture.

4. Есть runtime fragmentation

Одновременно:
- runtime/
- master runtime
- behavioral runtime
- autonomous runtime

5. High risk duplicated parquet writers/readers

Нужно отдельно audit:
- to_parquet
- read_parquet

6. Возможны hardcoded local paths

Нужно отдельно проверить результаты:
grep -R "/Users/" .

7. Archive/legacy физически находятся внутри active repo

Это будет:
- раздувать migration
- усложнять orchestration
- ломать dependency clarity

8. Нет явного separation:
- production engines
- research engines
- replay systems
- validation systems

9. initiative_memory_engine family выглядит как major migration risk

Слишком много evolution branches.

10. behavioral/runtime/orchestrator overlap

Нужна future consolidation после migration stabilization.
