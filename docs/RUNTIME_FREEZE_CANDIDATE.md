# RUNTIME FREEZE CANDIDATE

**Status:** Phase 4A — stable baseline before migration  
**Updated:** 2026-05-27  
**Tag target:** `phase-4a-canonical-consolidation`

---

## 1. Frozen Runtime Architecture

| Layer | Canonical module(s) | Status |
|-------|---------------------|--------|
| Orchestration | `run.py`, `src/btc_ml/runtime/pipeline.py`, `master_auction_runtime_v1.py` | Freeze candidate |
| Stage 2 cognition | `stage2_cognition_runtime_v1.py` | Frozen |
| Climax ontology | `auction_climax_engine_v1.py`, `ontology_refinement.py` | Frozen (Phase 3A) |
| Probabilistic runtime | `probabilistic_auction_engine_v1.py` | Frozen |
| Reinforcement | `auction_reinforcement_engine_v1.py` | Frozen |
| Calibration | `calibration_discipline.py`, `calibration_diagnostics.py` | Frozen (Phase 1B) |
| Adversarial | `adversarial_diagnostics.py` | Frozen (Phase 2B) |
| Stabilization | `ontology_stabilization.py` | Frozen (Phase 3B) |

**Pipeline:** 17 steps — see `src/btc_ml/runtime/pipeline.py::CANONICAL_PIPELINE`

---

## 2. Canonical Runtime Dependencies

```
live_market_feed.parquet
  → candle_structure_engine_v1
  → volume_classification / volume_response
  → stage2_cognition_runtime (climax + MTF)
  → runtime_cognition_engine
  → reinforcement → probabilistic
  → decay → state_transition → meta
```

Parquet contract: `docs/PARQUET_DEPENDENCY_MAP.md`

---

## 3. Active Feature Flags Inventory

| Flag | Default | Module |
|------|---------|--------|
| `ENABLE_PROBABILISTIC_DISCIPLINE` | `false` | `config/calibration.py` |
| `USE_DISCIPLINED_CONVICTION_AT_RUNTIME` | `false` | `config/calibration.py` |
| `CALIBRATION_MODE` | `raw` | `config/calibration.py` |
| `ENABLE_ONTOLOGY_REFINEMENT` | `true` | `config/ontology.py` |
| `USE_LEGACY_CLIMAX_ONTOLOGY` | `false` | `config/ontology.py` |
| `ENABLE_ADVERSARIAL_DIAGNOSTICS` | `false` | `config/adversarial.py` |
| `ENABLE_STRESS_SENSITIVITY` | `false` | `config/adversarial.py` |
| `ENABLE_ONTOLOGY_STABILIZATION` | `true` | `config/stabilization.py` |
| `ENABLE_FINAL_VALIDATION` | `true` | `config/replay.py` |

Unified access: `import config`

---

## 4. Frozen Ontology Inventory

| Class | Phase | Notes |
|-------|-------|-------|
| `STOPPING_VOLUME` | 3A | Absorption — effort/result `< 0.85` |
| `SELLING_CLIMAX` | 3A | Capitulation — effort/result `> 1.20` |
| `BUYING_CLIMAX` | Pre-3A | Under exhaustion audit (3B) |
| `HIGH_AVERAGE_VOLUME` | Pre-3A | Under ambiguity audit (3B) |
| Grey zone | 3A | No forced labeling `0.85–1.20` |

**No new ontology classes after Phase 3A.**

---

## 5. Frozen Replay Infrastructure

| Suite | Path |
|-------|------|
| Phase 1A calibration | `scripts/replay_validation/` |
| Phase 2A cross-regime | `scripts/replay_validation/cross_regime/` |
| Phase 2B adversarial | `scripts/replay_validation/adversarial/` |
| Phase 3A ontology | `scripts/replay_validation/ontology/` |
| Phase 3B stabilization | `scripts/replay_validation/stabilization/` |
| Phase 4A final validation | `scripts/replay_validation/final_validation/` |

Verification chain: `verify_phase0b` → `verify_phase3b` → `verify_phase4a_consolidation.py`

---

## 6. Entry Points

```bash
./run.sh              # canonical loop
./run.sh --once       # single pass
./run.sh --verify     # Phase 4A verification
python3 master_auction_runtime_v1.py  # legacy (deprecated)
```

---

*See also: `docs/CANONICAL_PLATFORM_ARCHITECTURE.md`, `docs/FINAL_RUNTIME_TOPOLOGY.md`*
