# INSTABILITY PROPAGATION MODEL

**Status:** Phase 2B — cascade detection  
**Updated:** 2026-05-27  
**Module:** `instability_propagation.py`

---

## 1. Purpose

Track how instability spreads across runtime cognition layers to detect cascading failures.

---

## 2. Propagation Layers

```text
alignment → reinforcement → persistence → contradiction → entropy → regime
```

Each layer emits an instability signal derived from existing exported metrics.

---

## 3. Exports

| Field | Meaning |
|-------|---------|
| `instability_origin` | First layer with elevated signal |
| `instability_propagation_chain` | Ordered chain of affected layers |
| `instability_persistence` | Consecutive cascade observations |
| `cascade_severity` | Normalized aggregate severity (0–1) |

---

## 4. Cascade Interpretation

| Severity | Interpretation |
|----------|----------------|
| < 0.20 | Isolated noise |
| 0.20–0.45 | Localized instability |
| > 0.45 | Potential cascading failure |

---

## 5. Replay

```bash
venv/bin/python3 scripts/replay_validation/adversarial/instability_cascade_replay.py
```

---

*See also: `docs/ADVERSARIAL_ROBUSTNESS_MODEL.md`, `docs/FAILURE_MODE_ANALYSIS.md`*
