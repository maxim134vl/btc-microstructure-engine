# CALIBRATION DRIFT MODEL

**Status:** Phase 2A — robustness observability  
**Updated:** 2026-05-27  
**Module:** `calibration_drift_engine.py`

---

## 1. Purpose

Detect gradual calibration degradation in disciplined runtime behavior using rolling baseline comparison. **Warning-only** — no automatic correction or threshold changes.

---

## 2. Drift Components

| Component | Detects |
|-----------|---------|
| `alignment_dominance_creep` | Alignment share rising vs baseline |
| `reinforcement_inflation_recurrence` | Reinforcement component above baseline |
| `entropy_suppression_weakening` | High conviction with rising entropy vs baseline |
| `contradiction_blindness` | Conflict density falling while conviction stays high |
| `saturation_relapse` | Conviction re-entering saturation after baseline was healthy |

---

## 3. Aggregate Metrics

| Export | Definition |
|--------|------------|
| `calibration_drift_score` | Mean normalized component score (0–1) |
| `drift_components` | JSON map of component values |
| `drift_direction` | `stable` \| `elevated` \| `degrading` |
| `drift_persistence_duration` | Consecutive elevated/degrading observations |

### Direction thresholds

| Direction | Condition |
|-----------|-----------|
| `degrading` | drift_score > 0.35 |
| `elevated` | drift_score > 0.15 |
| `stable` | otherwise |

---

## 4. Baseline Method

- Rolling window: last **50** probabilistic rows (configurable via `BASELINE_WINDOW`)
- Current row compared against baseline means/distributions
- Warning logged via `log_drift_warning()` when direction ≠ stable

---

## 5. Runtime Integration

Computed in `probabilistic_auction_engine_v1.py` after discipline exports and written to `probabilistic_auction_memory.parquet`.

---

## 6. Replay

```bash
venv/bin/python3 scripts/replay_validation/cross_regime/calibration_drift_replay.py
```

---

## 7. Non-Goals

- No automatic discipline strength adjustment
- No threshold retuning
- No execution or portfolio effects

---

*See also: `docs/CROSS_REGIME_CALIBRATION_ANALYSIS.md`, `docs/REGIME_TRANSITION_MODEL.md`*
