# Final Platform Freeze

**Phase:** 4B — Final Normalization & Operational Hardening  
**Status:** **Freeze candidate** — stable baseline before any execution-layer work  
**Version:** `0.5.0` (`phase-4b-normalization-hardening`)

---

## Architectural Statement

The project operates as a **canonical behavioral cognition platform**:

- Replayable
- Drift-aware
- Adversarially validated
- Ontology-stabilized
- Operationally orchestrated
- Structurally governable

**Not** an evolving flat runtime repository.

---

## Canonical Runtime Map

```
./run.sh
  └── run.py
        ├── runtime_hardening.py (startup gate)
        └── btc_ml.runtime.pipeline
              └── 17-step CANONICAL_PIPELINE
                    └── root *_engine_v1.py (frozen logic)
```

| Step | Engine |
|------|--------|
| 1 | candle_structure_engine_v1.py |
| 2 | volume_classification_engine_v1.py |
| 3 | schema_validation_engine_v1.py |
| 4 | behavioral_sequence_memory_v1.py |
| 5 | behavioral_volume_observer_v1.py |
| 6 | microstructure_candle_engine_v1.py |
| 7 | volume_response_engine_v1.py |
| 8 | climactic_behavior_engine_v1.py |
| 9 | auction_convergence_engine_v1.py |
| 10 | auction_synthesis_engine_v1.py |
| 11 | stage2_cognition_runtime_v1.py |
| 12 | runtime_cognition_engine_v1.py |
| 13 | auction_reinforcement_engine_v1.py |
| 14 | probabilistic_auction_engine_v1.py |
| 15 | auction_decay_engine_v1.py |
| 16 | state_transition_engine_v1.py |
| 17 | adaptive_meta_cognition_engine_v1.py |

---

## Frozen Ontology Map

| State | Module | Phase |
|-------|--------|-------|
| SELLING_CLIMAX vs STOPPING_VOLUME separation | `ontology_refinement.py` | 3A |
| Mutual exclusion, grey zone, effort/result | `auction_climax_engine_v1.py` | 3A |
| Stabilization audits (no expansion) | `ontology_stabilization.py` | 3B |
| Topology audit | `ontology_topology_audit.py` | 4A |

**Frozen:** No ontology semantic changes post-3B without explicit governance.

---

## Frozen Probabilistic Map

| Component | Module | Default |
|-----------|--------|---------|
| Calibration diagnostics | `calibration_diagnostics.py` | On |
| Probabilistic discipline | `probabilistic_discipline.py` | Off |
| Cross-regime robustness | Phase 2A suite | Validated |
| Adversarial diagnostics | `adversarial_*` | Off |

**Frozen:** Threshold gates, calibration redesign, conviction logic.

---

## Replay Infrastructure Inventory

| Suite | Path |
|-------|------|
| Cross-regime | `scripts/replay_validation/cross_regime/` |
| Adversarial | `scripts/replay_validation/adversarial/` |
| Ontology | `scripts/replay_validation/ontology/` |
| Stabilization | `scripts/replay_validation/stabilization/` |
| Final validation | `scripts/replay_validation/final_validation/` |

Outputs: `artifacts/`, `reports/`, `replays/`

---

## Operational Topology

```
config/                    # Unified flags
storage/path_registry.py   # Parquet truth
data/                      # Canonical parquet storage
runtime_hardening.py       # Fail-fast gate
scripts/bootstrap_runtime.sh
scripts/final_repo_audit.py
scripts/verify_phase4b_hardening.py
archive_removed/           # Backups + mirror archive
```

---

## Active Feature-Flag Inventory

| Flag | Default | Phase |
|------|---------|-------|
| `ENABLE_PROBABILISTIC_DISCIPLINE` | false | 1B |
| `USE_DISCIPLINED_CONVICTION_AT_RUNTIME` | false | 1B |
| `ENABLE_ADVERSARIAL_DIAGNOSTICS` | false | 2B |
| `ENABLE_STRESS_SENSITIVITY` | false | 2B |
| `ENABLE_ONTOLOGY_REFINEMENT` | true | 3A |
| `USE_LEGACY_CLIMAX_ONTOLOGY` | false | 3A |
| `ENABLE_ONTOLOGY_STABILIZATION` | true | 3B |
| `ENABLE_FINAL_VALIDATION` | true | 4A |
| `BTC_ML_DATA_ROOT` | data | 4B |

---

## Remaining Technical Debt

| Item | Priority |
|------|----------|
| Root engine → `src/btc_ml/services/` migration | P1 |
| Root shim removal after import normalization | P1 |
| Full `pd.read_parquet` → registry in non-pipeline scripts | P2 |
| `src/btc_ml/replay/` re-exports | P2 |
| Makefile / ruff / pytest CI | P3 |
| Root README consolidation | P3 |

---

## Explicitly Out of Scope

- Execution optimization
- PnL optimization
- Autonomous trading
- Portfolio construction
- Self-modifying systems
- Ontology redesign
- Calibration redesign

---

## Phase Tag Lineage

```
phase-0b-runtime-integrity
phase-1a-calibration-diagnostics
phase-1b-probabilistic-discipline
phase-2a-cross-regime-robustness
phase-2b-adversarial-robustness
phase-3a-ontology-refinement
phase-3b-ontology-stabilization
phase-4a-canonical-consolidation
phase-4b-normalization-hardening  ← current freeze candidate
```

---

*This document defines the stable platform baseline. Future execution-layer work must branch from this checkpoint.*
