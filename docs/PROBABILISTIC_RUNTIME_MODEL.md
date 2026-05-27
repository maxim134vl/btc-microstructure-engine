# PROBABILISTIC RUNTIME MODEL

**Status:** Canonical reference (Phase 1B discipline)  
**Updated:** 2026-05-27  
**Runtime engine:** `probabilistic_auction_engine_v1.py`

---

## 1. Model Overview

The probabilistic runtime layer converts reinforcement-window observations and Stage 2 cognition context into regime-labeled probability exports. Phase 1A adds a **diagnostic envelope** around the existing model without changing its decision math.

```text
reinforcement window (25 rows)
    + runtime cognition (STATE)
        → base probabilities (absorption / distribution / conviction)
        → cognition multipliers (exhaustion, rank, alignment, location)
        → final conviction_probability  ← RUNTIME OUTPUT
        → diagnostic exports            ← OBSERVABILITY ONLY
```

---

## 2. Inputs

| Input | Source | Used for |
|-------|--------|----------|
| Reinforcement window | `STATE["auction_reinforcement"]` | Base probability counts |
| `synthesis_state` | `STATE["runtime_cognition"]` | LOCAL_EXHAUSTION adjustment |
| `structural_rank` | cognition | HIGH rank multiplier |
| `alignment_score` + `alignment_status` | cognition | Alignment multiplier (VALID only) |
| `persistence_score` | cognition | Regime override + export |
| `location_bias` | cognition | Location multipliers |
| `unfinished_auction` | `STATE["volume_response"]` | Export observability |
| Reinforcement latest row | window tail | conflict_penalty propagation |

---

## 3. Core Probability Construction (Unchanged)

### Base window ratios

```text
absorption_probability    = absorption_count / window_size
distribution_probability  = distribution_count / window_size
conviction_probability    = high_conviction_count / window_size
```

### Regime assignment (unchanged thresholds)

| Regime | Condition |
|--------|-----------|
| `DISTRIBUTION_REGIME` | distribution_probability > 0.6 |
| `ABSORPTION_REGIME` | absorption_probability > 0.5 |
| `HIGH_CONVICTION_AUCTION` | conviction_probability > 0.7 |
| `STRUCTURAL_REGIME` | persistence_score > 0.7 |
| `UNCERTAIN` | default |

### Cognition multipliers (unchanged)

| Condition | Conviction effect |
|-----------|-------------------|
| `LOCAL_EXHAUSTION` | × 0.7 |
| `structural_rank == HIGH` | × 1.25 |
| alignment VALID | × (1 + alignment_score) |
| `LOWER_ABSORPTION` | × 1.15 |
| `UPPER_DISTRIBUTION` | × 0.75 |
| `MID_AUCTION_TRANSFER` | × 0.85 |

Final values clamped to `[0, 1]`.

---

## 4. Runtime vs Diagnostic Outputs

| Field | Used at runtime? | Description |
|-------|------------------|-------------|
| `conviction_probability` | **Yes** (raw by default) | Runtime conviction — equals `raw_conviction` unless discipline flag enabled |
| `raw_conviction` | Diagnostic | Pre-discipline conviction from frozen math |
| `disciplined_conviction` | No | Post-discipline shaped conviction |
| `calibrated_conviction` | Optional | Sigmoid of disciplined value when `CALIBRATION_MODE=sigmoid` |
| `saturation_*` | No | Saturation diagnostics |
| `persistence_duration` etc. | No | Survival tracking |
| `conflict_density` etc. | No | Contradiction observability |
| decomposition fields | No | Phase 0B observability |

---

## 5. Decomposition Fields (Phase 0B)

| Field | Captured at |
|-------|-------------|
| `reinforcement_component` | Base conviction ratio before cognition multipliers |
| `alignment_component` | Alignment multiplier (1.0 if invalid) |
| `persistence_component` | persistence_score export |
| `location_component` | Location multiplier product |
| `unfinished_auction_component` | 0/1 observability flag |
| `entropy_penalty` | Shannon entropy of belief window |
| `conflict_penalty` | Latest reinforcement conflict score |

These fields explain **how** conviction was composed but do not alter the composition.

---

## 6. Phase 1B Discipline Pipeline

When `ENABLE_PROBABILISTIC_DISCIPLINE=true`:

```text
raw_conviction (frozen math)
    × reinforcement_damping_factor
    × entropy_discipline_factor
    × persistence_realism_factor
    × contradiction_control_factor
    → logistic_compress (optional)
    → disciplined_conviction
    → calibrated_conviction (sigmoid export)
```

Runtime output (`conviction_probability`) follows `CALIBRATION_MODE` only when
`USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true`.

**Regime thresholds remain on raw path** — discipline does not alter threshold gates.

Reinforcement engine applies `apply_reinforcement_discipline()` when discipline enabled.

---

## 7. Phase 1A Diagnostic Envelope

Implemented in `calibration_diagnostics.build_diagnostic_exports()`:

### Saturation layer
Detects ceiling effects, reinforcement acceleration, alignment monoculture, and entropy suppression failure.

### Persistence survival layer
Measures regime continuity and decay velocity for tracked behavioral states.

### Conflict density layer
Quantifies contradictory co-active signals without applying new penalties.

### Sigmoid wrapper
Prepares nonlinear calibration infrastructure:

```python
calibrated_conviction = 1 / (1 + exp(-raw_conviction))
```

---

## 8. Memory Contract

**File:** `probabilistic_auction_memory.parquet`

**Write pattern:** `append_state_row()` via `state_guard.should_persist_state()`

**Persistence trigger:** regime change or any diagnostic/decomposition field change

**Lineage columns:** from Phase 0B (`lineage_*`)

---

## 9. Upstream / Downstream

```text
runtime_cognition_memory.parquet
    → runtime_cognition_engine_v1.py → STATE
        → auction_reinforcement_engine_v1.py
            → probabilistic_auction_engine_v1.py
                → probabilistic_auction_memory.parquet
                    → state_transition_engine_v1.py
                    → adaptive_meta_cognition_engine_v1.py
```

---

## 10. Diagnostic Consumption

| Tool | Purpose |
|------|---------|
| `conviction_realism_audit.py` | Static distribution analysis → markdown report |
| `scripts/replay_validation/conviction_evolution.py` | Temporal conviction trace |
| `scripts/replay_validation/saturation_progression.py` | Saturation timeline |
| `scripts/replay_validation/contradiction_emergence.py` | Conflict density timeline |
| `scripts/verify_phase1b_discipline.py` | Phase 1B discipline gate |
| `scripts/replay_validation/discipline_comparison.py` | Before/after replay |
| `phase_1b_calibration_results.py` | Results report generator |

---

## 11. Frozen Boundaries

The following remain **unchanged** unless discipline flags explicitly enabled:

- All regime thresholds (0.5, 0.6, 0.7)
- All cognition multipliers (0.7, 1.25, 1.15, etc.)
- Base reinforcement belief_strength composition
- Climax / synthesis ontology
- Execution and portfolio layers

---

*See also: `docs/CALIBRATION_FRAMEWORK.md`, `docs/CONVICTION_REALISM_AUDIT.md`, `docs/PHASE_1B_CALIBRATION_RESULTS.md`, `docs/RUNTIME_LINEAGE_MAP.md`*
