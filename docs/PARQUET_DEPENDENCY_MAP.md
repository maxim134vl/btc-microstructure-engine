# PARQUET DEPENDENCY MAP

**Status:** Canonical reference (root repository)  
**Updated:** 2026-05-26  
**Scope:** Production auction cognition pipeline + Stage 2 extensions  
**Source tree:** Repository root (`/Users/fontecrypto/btc-ml`) — **canonical**  
**Deprecated mirror:** `btc-microstructure-engine/` — do not use for lineage

---

## Legend

| Symbol | Meaning |
|--------|---------|
| `→` | Data flows from producer to consumer |
| `[LIVE]` | Written during live runtime loop |
| `[BATCH]` | Written by batch/research job only |
| `[STATE]` | Loaded into `state_manager_v1.STATE` at import/refresh |
| `[GAP]` | Known wiring gap — not yet in canonical runtime loop |

---

## 1. Canonical Production Lineage (Target)

```mermaid
flowchart TD
    subgraph ingestion [Ingestion]
        MF[multi_exchange_flow.parquet]
        LMF[live_market_feed.parquet]
    end

    subgraph structure [Structure Layer]
        CS[candle_structure_memory.parquet]
        VC[volume_classification_memory.parquet]
        BS[behavioral_sequence_memory.parquet]
        MC[microstructure_candle_memory.parquet]
        VR[volume_response_state.parquet]
    end

    subgraph auction [Auction Layer]
        CB[climactic_behavior_memory.parquet]
        AC[auction_convergence_memory.parquet]
        AS[auction_synthesis_memory.parquet]
    end

    subgraph stage2 [Stage 2 Cognition - GAP in runtime loop]
        MTF[multi_timeframe_synthesis.parquet]
        RC[runtime_cognition_memory.parquet]
    end

    subgraph cognition [Cognition Layer]
        AR[auction_reinforcement_memory.parquet]
        PA[probabilistic_auction_memory.parquet]
        AD[auction_decay_memory.parquet]
        ST[state_transition_memory.parquet]
        AM[adaptive_meta_cognition_state.parquet]
    end

    MF --> CS
    CS --> VC
    CS --> BS
    CS --> MC
    VC --> VR
    BS --> VR
    VR --> CB
    VR --> AC
    AC --> AS
    AS --> AR
    AS --> PA
    AR --> PA
    AC --> AD
    AR --> AD
    AS --> ST
    PA --> ST
    PA --> AM
    AR --> AM

    CS -.->|climax reads STATE| CLX[auction_climax_engine_v1]
    CLX -.-> MTF
    MTF -.-> RC
    RC -.->|runtime_cognition_engine| STATE2[STATE runtime_cognition]
```

---

## 2. Master Auction Runtime — Engine × Parquet Matrix

Orchestrator: **`master_auction_runtime_v1.py`** (canonical)

| # | Engine | Reads | Writes | Mode |
|---|--------|-------|--------|------|
| 1 | `candle_structure_engine_v1.py` | `multi_exchange_flow.parquet` | `candle_structure_memory.parquet` | `[LIVE]` |
| 2 | `volume_classification_engine_v1.py` | `candle_structure_memory.parquet` | `volume_classification_memory.parquet` | `[LIVE]` |
| 3 | `schema_validation_engine_v1.py` | *(in-memory / schema registry)* | — | `[LIVE]` |
| 4 | `behavioral_sequence_memory_v1.py` | `temporal_context_memory.parquet`, `volume_localization_v2_memory.parquet`, `volume_reactions.parquet`, `behavioral_events_memory.parquet` | `behavioral_sequence_memory.parquet` | `[LIVE]` |
| 5 | `behavioral_volume_observer_v1.py` | `behavioral_sequence_memory.parquet`, `volume_localization_v2_memory.parquet`, `volume_reactions.parquet`, `behavioral_events_memory.parquet`, `temporal_context_memory.parquet`, `contextual_memory_state.parquet`, `adaptive_behavioral_weights.parquet` | `behavioral_observer_state.parquet` | `[LIVE]` |
| 6 | `microstructure_candle_engine_v1.py` | `btc_15m.parquet` | `microstructure_candle_memory.parquet` | `[LIVE]` ⚠ legacy input |
| 7 | `volume_response_engine_v1.py` | `candle_structure_memory.parquet`, `volume_classification_memory.parquet`, `candle_geometry_v2_memory.parquet`, `volume_localization_v2_memory.parquet`, `volume_reactions.parquet`, `volume_response_state.parquet` | `volume_response_state.parquet` | `[LIVE]` |
| 8 | `climactic_behavior_engine_v1.py` | `volume_response_state.parquet`, `climactic_behavior_memory.parquet` | `climactic_behavior_memory.parquet` | `[LIVE]` |
| 9 | `auction_convergence_engine_v1.py` | `volume_response_state.parquet`, `auction_convergence_memory.parquet` | `auction_convergence_memory.parquet` | `[LIVE]` |
| 10 | `auction_synthesis_engine_v1.py` | `volume_response_state.parquet`, `auction_convergence_memory.parquet`, `auction_synthesis_memory.parquet`, `htf_structure_memory.parquet`, `htf_ltf_context_memory.parquet` | `auction_synthesis_memory.parquet` | `[LIVE]` |
| 11 | `runtime_cognition_engine_v1.py` | `runtime_cognition_memory.parquet`, `multi_timeframe_synthesis.parquet` | — (writes to `STATE["runtime_cognition"]`) | `[LIVE]` ⚠ needs upstream batch |
| 12 | `auction_reinforcement_engine_v1.py` | `auction_reinforcement_memory.parquet`, `STATE` synthesis/convergence | `auction_reinforcement_memory.parquet` | `[LIVE]` |
| 13 | `probabilistic_auction_engine_v1.py` | `STATE` reinforcement | `probabilistic_auction_memory.parquet` | `[LIVE]` |
| 14 | `auction_decay_engine_v1.py` | `auction_convergence_memory.parquet`, `auction_reinforcement_memory.parquet`, `auction_decay_memory.parquet` | `auction_decay_memory.parquet` | `[LIVE]` |
| 15 | `state_transition_engine_v1.py` | `auction_synthesis_memory.parquet`, `probabilistic_auction_memory.parquet`, `state_transition_memory.parquet` | `state_transition_memory.parquet`, `state_transition_engine_state.parquet` | `[LIVE]` |
| 16 | `adaptive_meta_cognition_engine_v1.py` | `STATE` probabilistic + reinforcement | `adaptive_meta_cognition_state.parquet` | `[LIVE]` |

---

## 3. Stage 2 Cognition — Batch Chain (Primary Production Direction)

These modules are **canonical at root** but currently run **outside** the master runtime loop (via `research_dataset_builder_v1.py` or manual invocation).

| Engine | Reads | Writes | Mode |
|--------|-------|--------|------|
| `auction_climax_engine_v1.py` | `STATE["candle_structure"]` ← `candle_structure_memory.parquet` | *(in-memory return only; no parquet write today)* | `[BATCH]` / `[GAP]` |
| `multi_timeframe_dataset_builder.py` | `research_master_dataset.parquet` | — | `[BATCH]` |
| `multi_timeframe_synthesis_engine.py` | climax outputs (in-memory), M15/M30/H1/H4 states | — (returns DataFrame) | `[BATCH]` |
| `research_dataset_builder_v1.py` | `live_market_feed.parquet`, `candle_structure_memory.parquet`, `volume_response_state.parquet`, `auction_convergence_memory.parquet`, `auction_synthesis_memory.parquet`, `probabilistic_auction_memory.parquet`, `auction_reinforcement_memory.parquet` | `research_master_dataset.parquet`, `multi_timeframe_synthesis.parquet`, `runtime_cognition_memory.parquet` | `[BATCH]` |

**Target wiring (migration — no logic change):** insert Stage 2 batch step between steps 10 and 11 in master runtime, or run as scheduled sub-process that refreshes `runtime_cognition_memory.parquet` before `runtime_cognition_engine_v1.py`.

---

## 4. STATE Registry (`state_manager_v1.py`)

Loaded at import via `refresh_state()`:

| STATE key | Parquet file | Writers | Readers |
|-----------|--------------|---------|---------|
| `candle_structure` | `candle_structure_memory.parquet` | `candle_structure_engine_v1` | climax, STATE refresh |
| `auction_synthesis` | `auction_synthesis_memory.parquet` | `auction_synthesis_engine_v1` | reinforcement, probabilistic, STATE |
| `auction_convergence` | `auction_convergence_memory.parquet` | `auction_convergence_engine_v1` | decay, reinforcement, STATE |
| `auction_reinforcement` | `auction_reinforcement_memory.parquet` | `auction_reinforcement_engine_v1` | probabilistic, decay, meta, STATE |
| `volume_response` | `volume_response_state.parquet` | `volume_response_engine_v1` | convergence, synthesis, climax path |
| `behavioral_sequence` | `behavioral_sequence_memory.parquet` | `behavioral_sequence_memory_v1` | observer, STATE |
| `probabilistic_auction` | `probabilistic_auction_memory.parquet` | `probabilistic_auction_engine_v1` | state_transition, meta, STATE |
| `adaptive_meta_cognition` | `adaptive_meta_cognition_state.parquet` | `adaptive_meta_cognition_engine_v1` | STATE |
| `runtime_cognition` | *(dict in memory)* | `runtime_cognition_engine_v1` | probabilistic, reinforcement |

---

## 5. Runtime Dependency Guard (`runtime_dependency_map.py`)

Partial gate — only 4 engines have explicit parquet prerequisites:

| Engine | Required files (must exist + be fresh) |
|--------|----------------------------------------|
| `auction_synthesis_engine_v1.py` | `volume_response_state.parquet`, `htf_structure_memory.parquet`, `htf_ltf_context_memory.parquet` |
| `probabilistic_auction_engine_v1.py` | `auction_synthesis_memory.parquet`, `auction_reinforcement_memory.parquet` |
| `state_transition_engine_v1.py` | `auction_synthesis_memory.parquet`, `probabilistic_auction_memory.parquet` |
| `auction_decay_engine_v1.py` | `auction_convergence_memory.parquet`, `auction_reinforcement_memory.parquet` |

**Gap:** Stage 2 files (`multi_timeframe_synthesis.parquet`, `runtime_cognition_memory.parquet`) not in guard map.

---

## 6. Parquet Lineage — Primary Memory Chain

```
multi_exchange_flow.parquet
    └── candle_structure_memory.parquet
            ├── volume_classification_memory.parquet
            ├── behavioral_sequence_memory.parquet
            └── volume_response_state.parquet
                    ├── climactic_behavior_memory.parquet
                    ├── auction_convergence_memory.parquet
                    └── auction_synthesis_memory.parquet
                            ├── auction_reinforcement_memory.parquet
                            │       ├── probabilistic_auction_memory.parquet
                            │       │       ├── state_transition_memory.parquet
                            │       │       └── adaptive_meta_cognition_state.parquet
                            │       └── auction_decay_memory.parquet
                            └── (Stage 2 branch)
                                    research_master_dataset.parquet
                                        └── multi_timeframe_synthesis.parquet
                                                └── runtime_cognition_memory.parquet
                                                        └── STATE["runtime_cognition"]
```

---

## 7. Secondary / Legacy Inputs (not in canonical auction path)

| File | Used by | Status |
|------|---------|--------|
| `btc_15m.parquet` | `microstructure_candle_engine_v1` | Legacy static input — review |
| `candle_geometry_v2_memory.parquet` | `volume_response_engine_v1` | Cross-pipeline bleed from microstructure v2 |
| `volume_localization_v2_memory.parquet` | behavioral engines | Cross-pipeline bleed |
| `htf_structure_memory.parquet` | `auction_synthesis_engine_v1` | Required by dependency guard |
| `htf_ltf_context_memory.parquet` | `auction_synthesis_engine_v1` | Required by dependency guard |
| `datasets/live/latest.parquet` | `live_binance_feed_v2.py` (root) | ⚠ diverges from `live_market_feed.parquet` |
| `live_market_feed.parquet` | `research_dataset_builder_v1`, deprecated mirror feed | Expected by research + microstructure |

---

## 8. Write Pattern Summary

| Pattern | Modules | Risk |
|---------|---------|------|
| `append_state_row()` | probabilistic, decay, state_transition, convergence | Dedup via `state_guard` |
| Direct `to_parquet()` overwrite | reinforcement, volume_response, candle_structure | Last-write-wins |
| `append_parquet()` | live_binance_feed_v2 (root) | Append-safe |
| In-memory only | auction_climax, multi_timeframe_synthesis | No persistence — `[GAP]` |
| Batch merge + export | research_dataset_builder_v1 | Research boundary |

---

## 9. Files to Populate in Schema Registry (future)

Priority parquet contracts for `schemas/` package:

1. `candle_structure_memory.parquet`
2. `volume_response_state.parquet`
3. `auction_synthesis_memory.parquet`
4. `auction_reinforcement_memory.parquet`
5. `probabilistic_auction_memory.parquet`
6. `multi_timeframe_synthesis.parquet`
7. `runtime_cognition_memory.parquet`

---

*See also: `docs/CANONICAL_RUNTIME_MAP.md`, `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`*
