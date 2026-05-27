# CANONICAL RUNTIME MAP

**Status:** Approved architecture  
**Updated:** 2026-05-26  
**Canonical orchestrator:** `master_auction_runtime_v1.py`  
**Canonical source tree:** Repository root  
**Deprecated:** `btc-microstructure-engine/` (mirror only)

---

## 1. Architectural Decisions (Approved)

| Decision | Resolution |
|----------|------------|
| Canonical runtime | `master_auction_runtime_v1.py` |
| Canonical source | Repository root |
| Deprecated mirror | `btc-microstructure-engine/` |
| Production direction | Stage 2 auction cognition pipeline |
| Diverged duplicates (12) | **Root versions canonical** |
| Behavioral logic | **Frozen** — no threshold/calibration changes during refactor |
| Scope of current work | Consolidation, mapping, migration prep only |

---

## 2. Production Runtime — Master Auction Loop

**Entry command (current):**

```bash
cd /Users/fontecrypto/btc-ml
venv/bin/python3 master_auction_runtime_v1.py
```

**Loop:** `while True` → 16 engines → `sleep(5)` → repeat

**Execution modes per engine:**

| Mode | Engines |
|------|---------|
| In-process via `engine_registry.ENGINES` | `auction_reinforcement_engine_v1`, `probabilistic_auction_engine_v1`, `adaptive_meta_cognition_engine_v1`, `auction_convergence_engine_v1` |
| Subprocess `python3 <engine>.py` | All others in pipeline |
| Gated by `runtime_dependency_guard` | synthesis, probabilistic, state_transition, decay |

---

## 3. Canonical Pipeline Order

```
PHASE 1 — STRUCTURE
  1. candle_structure_engine_v1.py
  2. volume_classification_engine_v1.py
  3. schema_validation_engine_v1.py
  4. behavioral_sequence_memory_v1.py
  5. behavioral_volume_observer_v1.py
  6. microstructure_candle_engine_v1.py
  7. volume_response_engine_v1.py

PHASE 2 — AUCTION BEHAVIOR
  8. climactic_behavior_engine_v1.py
  9. auction_convergence_engine_v1.py
  10. auction_synthesis_engine_v1.py

PHASE 3 — STAGE 2 COGNITION (primary direction — partial wiring)
  [GAP] auction_climax_engine_v1.py          ← not in loop yet
  [GAP] multi_timeframe_synthesis_engine.py ← not in loop yet
  [BATCH] research_dataset_builder_v1.py    ← produces MTF + cognition parquet
  11. runtime_cognition_engine_v1.py        ← in loop; reads batch output

PHASE 4 — REINFORCEMENT & PROBABILITY
  12. auction_reinforcement_engine_v1.py
  13. probabilistic_auction_engine_v1.py
  14. auction_decay_engine_v1.py
  15. state_transition_engine_v1.py
  16. adaptive_meta_cognition_engine_v1.py
```

---

## 4. Stage 2 Cognition Stack (Primary Production Direction)

| Layer | Module | Role | In master loop? |
|-------|--------|------|-----------------|
| Climax detection | `auction_climax_engine_v1.py` | M15 climax events + execution distribution | **No** — manual/batch |
| MTF aggregation | `multi_timeframe_dataset_builder.py` | Resample M30/H1/H4/D1 | **No** — via builder |
| MTF synthesis | `multi_timeframe_synthesis_engine.py` | LOCAL_EXHAUSTION / INTERMEDIATE / STRUCTURAL | **No** — via builder |
| Cognition export | `research_dataset_builder_v1.py` | Writes `runtime_cognition_memory.parquet` | **No** — batch only |
| Runtime load | `runtime_cognition_engine_v1.py` | Loads cognition → `STATE` | **Yes** — step 11 |
| Reinforcement | `auction_reinforcement_engine_v1.py` | Reads `STATE["runtime_cognition"]` | **Yes** — step 12 |
| Probabilistic | `probabilistic_auction_engine_v1.py` | Regime probabilities | **Yes** — step 13 |
| Meta cognition | `adaptive_meta_cognition_engine_v1.py` | Stability / meta layer | **Yes** — step 16 |

**Migration target:** Stage 2 batch chain runs automatically before step 11 (or as dedicated sub-orchestrator), without changing detection thresholds.

---

## 5. Deprecated Runtimes (Do Not Use for Production)

| Runtime | Location | Reason deprecated |
|---------|----------|-------------------|
| `autonomous_runtime_v2.py` | root + mirror | Docker microstructure pipeline — not canonical |
| `autonomous_runtime_v1.py` | root + mirror | Superseded |
| `runtime/run_canonical_pipeline.py` | root + mirror | README legacy path |
| `behavioral_runtime_loop_v1.py` | root + mirror | Parallel legacy |
| `runtime/live_engine_runner.py` | root + mirror | ML inference legacy |
| `btc-microstructure-engine/docker-compose.yml` | mirror | Points at non-canonical runtime |

These remain in repo until `archive_removed/` migration. **Do not extend.**

---

## 6. Data Ingestion (Supporting — Not Orchestrated by Master)

| Collector | Output | Canonical? |
|-----------|--------|------------|
| `collectors/multi_exchange_collector.py` | `multi_exchange_flow.parquet` | Yes — feeds candle_structure |
| `live_binance_feed_v2.py` (root) | `datasets/live/latest.parquet` | ⚠ path mismatch — see boundary doc |
| `collectors/orderbook_collector.py` | orderbook parquet | Supporting |
| `collectors/oi_collector.py` | OI parquet | Supporting |
| `collectors/liquidation_collector.py` | liquidation parquet | Supporting |

**Note:** Collectors run as separate long-lived processes, not inside master auction loop.

---

## 7. Research / Dev Entry Points (Non-Production)

| Script | Purpose |
|--------|---------|
| `research_dataset_builder_v1.py` | Full Stage 2 batch pipeline |
| `multi_timeframe_synthesis_engine.py` | Standalone synthesis test |
| `auction_climax_engine_v1.py` | Standalone climax test |
| `probabilistic_auction_engine_v1.py` | Standalone (has `__main__`) |
| `research/replay/*.py` | Historical replay |
| `*_backtest_v1.py` | One-off backtests |

---

## 8. Infrastructure Modules (Canonical Root)

| Module | Role |
|--------|------|
| `state_manager_v1.py` | STATE singleton + parquet loaders |
| `parquet_utils.py` | Safe read / append |
| `state_guard.py` | Dedup persistence |
| `runtime_dependency_map.py` | Parquet prerequisites |
| `runtime_dependency_guard.py` | Engine gating |
| `runtime_state_manager.py` | Loop health tracking |
| `engine_registry.py` | In-process engine dispatch |
| `runtime_config.py` | Path constants |

---

## 9. Target Runtime After `src/btc_ml/` Migration

```
btc_ml orchestration.auction_pipeline.run()
    ├── phase_structure()
    ├── phase_auction()
    ├── phase_stage2_cognition()   ← new orchestration wrapper, same logic
    ├── phase_reinforcement()
    └── phase_probabilistic()
```

Thin wrapper at repo root during transition:

```python
# master_auction_runtime_v1.py  (deprecated shim)
from btc_ml.orchestration.auction_pipeline import run
run()
```

---

## 10. Documentation Alignment Required

| Document | Current state | Action |
|----------|---------------|--------|
| `docs/SYSTEM_MAP.md` | Names master auction — **aligned** | Update Stage 2 section |
| `README_RUNTIME.md` | Points to `run_canonical_pipeline` — **conflicts** | Mark deprecated |
| `btc-microstructure-engine/docker-compose.yml` | Points to autonomous v2 — **conflicts** | Mark deprecated |
| `docs/PARQUET_DEPENDENCY_MAP.md` | **This audit output** | Keep updated |

---

*See also: `docs/DUPLICATE_RESOLUTION_PLAN.md`, `docs/MIGRATION_PLAN_SRC_BTC_ML.md`*
