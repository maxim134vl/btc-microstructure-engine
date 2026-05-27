# CONVICTION REALISM AUDIT

**Generated:** 2026-05-27T09:55:14.141433+00:00  
**Phase:** 1A — Probabilistic Calibration Diagnostics  
**Scope:** Observability only — no calibration changes applied

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **4**
- Reinforcement rows analyzed: **5**
- HIGH_CONVICTION belief rows: **0**

## 2. Component Contribution Distribution

### Probabilistic Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.388 | 0.388 | 0.390 | 0.391 |
| `conflict_penalty` | 0.093 | 0.093 | 0.094 | 0.094 |
| `entropy_penalty` | 0.211 | 0.212 | 0.228 | 0.232 |
| `persistence_component` | 0.078 | 0.078 | 0.078 | 0.078 |
| `reinforcement_component` | 0.230 | 0.230 | 0.246 | 0.250 |

### Reinforcement Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.034 | 0.034 | 0.036 | 0.037 |
| `conflict_penalty` | 0.163 | 0.161 | 0.172 | 0.176 |
| `entropy_penalty` | 0.316 | 0.322 | 0.353 | 0.359 |
| `persistence_component` | 0.027 | 0.027 | 0.029 | 0.029 |
| `reinforcement_component` | 0.461 | 0.456 | 0.489 | 0.498 |

## 3. Dominant Component Frequency

### Probabilistic Dominant Component

| Component | Frequency |
|-----------|-----------|
| `alignment_component` | 1.000 |

### Reinforcement Dominant Component

| Component | Frequency |
|-----------|-----------|
| `reinforcement_component` | 1.000 |

## 4. Required Diagnostic Metrics

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Reinforcement persistence duration (est.) | 5 | Consecutive identical belief_state at tail |
| Entropy suppression frequency | 0.000 | High conviction with low entropy penalty |
| Conviction saturation frequency | 0.000 | Share of rows with conviction > 0.90 |
| Alignment dominance ratio | 0.388 | Mean alignment share of decomposition mass |
| Mean conviction probability | 0.745 | Central tendency of exported conviction |
| Mean entropy penalty | 0.679 | Belief-state entropy observability |
| Mean conflict penalty (probabilistic) | 0.300 | Conflict signal propagated from reinforcement |

## 5. Component Focus

### alignment_component
Measures MTF alignment multiplier (probabilistic) or additive delta (reinforcement). High dominance suggests structural agreement is driving conviction more than conflict or entropy signals.

### persistence_component
Exports persistence score / additive persistence contribution. Low values with high conviction indicate weak persistence realism.

### reinforcement_component
Base reinforcement contribution before cognition multipliers. Rising tail values with saturation flags indicate reinforcement inflation.

### entropy_penalty
Shannon entropy of belief-state window (observability only). Low entropy with high conviction indicates entropy suppression failure.

### conflict_penalty
Conflict score propagated from reinforcement path. Low conflict with high conviction suggests contradiction density is under-expressed.

## 6. Realism Verdict

**Assessment:** Runtime shows **mixed probabilistic behavior** — some overconfidence signals present but not uniformly dominant.

## 7. Raw Metrics JSON

```json
{
  "probabilistic_rows_analyzed": 4,
  "reinforcement_rows_analyzed": 5,
  "probabilistic_component_distribution": {
    "alignment_component": {
      "mean_share": 0.3883565629926863,
      "median_share": 0.38779891282133944,
      "p90_share": 0.389884281716365,
      "max_share": 0.3905660601340693
    },
    "persistence_component": {
      "mean_share": 0.07767131259853724,
      "median_share": 0.07755978256426788,
      "p90_share": 0.077976856343273,
      "max_share": 0.07811321202681386
    },
    "reinforcement_component": {
      "mean_share": 0.22995035008732517,
      "median_share": 0.22957277494802117,
      "p90_share": 0.24579832303055313,
      "max_share": 0.24996227848580438
    },
    "entropy_penalty": {
      "mean_share": 0.21081619920320666,
      "median_share": 0.2120270262982616,
      "p90_share": 0.2278954254324881,
      "max_share": 0.23158814929516763
    },
    "conflict_penalty": {
      "mean_share": 0.0932055751182447,
      "median_share": 0.09307173907712148,
      "p90_share": 0.09357222761192763,
      "max_share": 0.09373585443217665
    }
  },
  "reinforcement_component_distribution": {
    "alignment_component": {
      "mean_share": 0.03386133366253175,
      "median_share": 0.03354834857763116,
      "p90_share": 0.03593350943680597,
      "max_share": 0.036639556118876475
    },
    "persistence_component": {
      "mean_share": 0.027089066930025402,
      "median_share": 0.026838678862104927,
      "p90_share": 0.028746807549444777,
      "max_share": 0.029311644895101182
    },
    "reinforcement_component": {
      "mean_share": 0.46051413781043193,
      "median_share": 0.4562575406557838,
      "p90_share": 0.48869572834056124,
      "max_share": 0.49829796321672015
    },
    "entropy_penalty": {
      "mean_share": 0.3160010600168585,
      "median_share": 0.32232335873185053,
      "p90_share": 0.3527518693298434,
      "max_share": 0.3592300444282348
    },
    "conflict_penalty": {
      "mean_share": 0.16253440158015245,
      "median_share": 0.16103207317262958,
      "p90_share": 0.17248084529666868,
      "max_share": 0.1758698693706071
    }
  },
  "probabilistic_dominant_component_frequency": {
    "alignment_component": 1.0
  },
  "reinforcement_dominant_component_frequency": {
    "reinforcement_component": 1.0
  },
  "reinforcement_persistence_duration_estimate": 5,
  "entropy_suppression_frequency": 0.0,
  "conviction_saturation_frequency": 0.0,
  "alignment_dominance_ratio": 0.3883565629926863,
  "high_conviction_state_count": 0,
  "mean_conviction_probability": 0.744625,
  "mean_entropy_penalty": 0.6787298305508566,
  "mean_conflict_penalty_probabilistic": 0.30000000000000004
}
```

---

*Regenerate:* `venv/bin/python3 conviction_realism_audit.py`
