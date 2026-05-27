# POST-SPLIT REINFORCEMENT ANALYSIS

**Status:** Phase 3B  
**Module:** `post_split_reinforcement_analysis.py`

---

## Exports

| Field | Meaning |
|-------|---------|
| `reinforcement_behavior_shift` | Mean reinforcement delta: STOPPING vs SELLING |
| `ontology_reinforcement_divergence` | Asymmetry magnitude between sell-side types |
| `reinforcement_stability_score` | Stability index (1.0 = stable) |

## Goal

Ensure absorption states do not become reinforcement-dominant after semantic split.
