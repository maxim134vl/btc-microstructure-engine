# ABSORPTION VS CAPITULATION

**Status:** Phase 3A — semantic separation model  
**Updated:** 2026-05-27  
**Module:** `ontology_refinement.py`

---

## 1. Behavioral Distinction

| Dimension | STOPPING_VOLUME (Absorption) | SELLING_CLIMAX (Capitulation) |
|-----------|------------------------------|------------------------------|
| Effort/result | High effort, weak result | High effort, large result |
| `efficiency_decay` | `< 0.85` | `> 1.20` |
| Close position | Upper third of range (`> 0.35`) | Lower quarter (`< 0.25`) |
| Lower wick | Prominent recovery (`> 0.25`) | Minimal recovery (`< 0.20`) |
| Delta behavior | Improving (less negative) | Aggressive continuation |
| `location_bias` | `LOWER_ABSORPTION` | `LOWER_CAPITULATION` |

---

## 2. Grey Zone Policy

When `efficiency_decay` is between 0.85 and 1.20:

- No `SELLING_CLIMAX` or `STOPPING_VOLUME` label applied
- Row may remain `NORMAL` or `HIGH_AVERAGE_VOLUME`
- **No forced labeling in ambiguous zones**

---

## 3. Swing-Cluster Deduplication

Within swing-low clusters (`range_position < 0.45`, within `SWING_CLUSTER_WINDOW` bars):

**Priority:** `STOPPING_VOLUME` > `SELLING_CLIMAX` > `HIGH_AVERAGE_VOLUME`

Only the strongest behavioral event is retained per cluster.

---

## 4. Replay Validation

```bash
venv/bin/python3 scripts/replay_validation/ontology/absorption_vs_capitulation.py
```

---

## 5. Adversarial Stability

Ontology separation is stress-tested via `adversarial_ontology_stability.py` under entropy shocks, fake breakouts, contradiction floods, liquidity vacuums, and regime flips.

---

*See also: `docs/POST_EVENT_BEHAVIORAL_EVOLUTION.md`*
