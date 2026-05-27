# EFFORT / RESULT SEMANTICS

**Status:** Phase 3A — primary behavioral discriminator  
**Updated:** 2026-05-27  
**Module:** `ontology_refinement.py`

---

## 1. Definition

**Effort** = high volume + spread participation at low range position  
**Result** = directional efficiency relative to recent baseline (`efficiency_decay`)

```text
efficiency_decay = directional_efficiency / rolling_mean_20
directional_efficiency = spread / volume
```

---

## 2. Classification Zones

| Zone | `efficiency_decay` | Semantic |
|------|-------------------|----------|
| Capitulation | `> 1.20` | Large directional result → `SELLING_CLIMAX` candidate |
| Absorption | `< 0.85` | Weak directional result → `STOPPING_VOLUME` candidate |
| Grey | `0.85–1.20` | No climax classification |

---

## 3. Secondary Discriminators

### SELLING_CLIMAX anatomy
- `close_position_ratio < 0.25`
- `lower_wick_ratio < 0.20`
- `delta_behavior_shift <= 0` (aggressive continuation)

### STOPPING_VOLUME anatomy
- `close_position_ratio > 0.35`
- `lower_wick_ratio > 0.25`
- `delta_behavior_shift > 0` (weakening seller aggression)

---

## 4. Delta Behavior Shift

```text
delta_behavior_shift = (delta - delta[t-1]) / |delta[t-1]|
```

Positive shift under negative delta = improving (absorption signal).  
Non-positive shift = sustained aggression (capitulation signal).

---

## 5. Non-Goals

- Not volume intensity ranking
- Not threshold optimization for PnL
- Not execution signal generation
