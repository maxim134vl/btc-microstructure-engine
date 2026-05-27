# FAILURE MODE ANALYSIS

**Status:** Phase 2B — probabilistic failure-mode detection  
**Updated:** 2026-05-27  
**Module:** `failure_mode_analysis.py`

---

## 1. Purpose

Detect probabilistic failure patterns in disciplined runtime behavior before they cascade into structural cognition collapse.

---

## 2. Failure Modes

| Mode | Detection signal |
|------|------------------|
| `CONVICTION_COLLAPSE` | Rapid conviction drop / discipline divergence |
| `RUNAWAY_REINFORCEMENT` | Runaway reinforcement flags + acceleration |
| `ENTROPY_BLINDNESS` | High conviction with low entropy penalty |
| `CONTRADICTION_SUPPRESSION_FAILURE` | Low conflict density under high conviction |
| `REGIME_TRANSITION_INSTABILITY` | High transition probability / regime drift |
| `CALIBRATION_DRIFT_ACCELERATION` | Elevated drift score with persistence |
| `UNSTABLE_PERSISTENCE_INHERITANCE` | High persistence component, low duration |
| `NONE` | No dominant failure signal |

---

## 3. Exports

| Field | Meaning |
|-------|---------|
| `failure_mode` | Dominant detected mode |
| `failure_probability` | Confidence in mode assignment (0–1) |
| `collapse_velocity` | Rate of conviction decline |
| `instability_cluster` | JSON list of co-active failure modes |
| `probabilistic_fragility_score` | Aggregate fragility index |

---

## 4. Interpretation

Failure modes represent **internal probabilistic coherence risks**, not trading edge failure. A high fragility score indicates the runtime may lose discipline under stress — not that a strategy is unprofitable.

---

## 5. Collapse Prevention

Phase 2B is observability-only. Failure detection does not alter conviction math. Future phases may use these signals for controlled discipline tightening.

---

*See also: `docs/ADVERSARIAL_ROBUSTNESS_MODEL.md`*
