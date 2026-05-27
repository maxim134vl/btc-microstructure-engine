# ONTOLOGY REFINEMENT MODEL

**Status:** Phase 3A — semantic ontology refinement  
**Updated:** 2026-05-27  
**Modules:** `ontology_refinement.py`, `auction_climax_engine_v1.py`

---

## 1. Purpose

Repair semantic collapse between `SELLING_CLIMAX` (capitulation) and `STOPPING_VOLUME` (absorption) without modifying signal architecture, thresholds, execution, or portfolio logic.

---

## 2. Core Principle

Effort/result behavior — not volume intensity — separates capitulation from absorption.

| Type | Effort/Result | Primary Discriminator |
|------|---------------|----------------------|
| `SELLING_CLIMAX` | High effort → large directional result | `efficiency_decay > 1.20` |
| `STOPPING_VOLUME` | High effort → weak directional result | `efficiency_decay < 0.85` |
| Grey zone | Ambiguous | `0.85–1.20` → no climax classification |

---

## 3. Assignment Order (Mutual Exclusion)

1. `BUYING_CLIMAX` (unchanged)
2. `HIGH_AVERAGE_VOLUME` (only if `NORMAL`)
3. **`STOPPING_VOLUME`** (only if `NORMAL`)
4. **`SELLING_CLIMAX`** (only if still `NORMAL`)

No overwrite behavior permitted.

---

## 4. Feature Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `ENABLE_ONTOLOGY_REFINEMENT` | `true` | Master refinement gate |
| `USE_LEGACY_CLIMAX_ONTOLOGY` | `false` | Rollback to legacy (includes lookahead) |

---

## 5. Verification

```bash
venv/bin/python3 scripts/verify_phase3a_ontology.py
venv/bin/python3 scripts/replay_validation/ontology/ontology_replay_runner.py
```

---

*See also: `docs/EFFORT_RESULT_SEMANTICS.md`, `docs/ABSORPTION_VS_CAPITULATION.md`*
