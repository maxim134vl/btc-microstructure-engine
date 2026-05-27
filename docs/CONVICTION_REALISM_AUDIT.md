# CONVICTION REALISM AUDIT

**Generated:** 2026-05-27T10:01:46.677940+00:00  
**Phase:** 1A — Probabilistic Calibration Diagnostics  
**Scope:** Observability only — no calibration changes applied

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **6**
- Reinforcement rows analyzed: **7**
- HIGH_CONVICTION belief rows: **0**

## 2. Component Contribution Distribution

### Probabilistic Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.389 | 0.388 | 0.390 | 0.391 |
| `conflict_penalty` | 0.093 | 0.093 | 0.094 | 0.094 |
| `entropy_penalty` | 0.223 | 0.225 | 0.246 | 0.251 |
| `persistence_component` | 0.078 | 0.078 | 0.078 | 0.078 |
| `reinforcement_component` | 0.218 | 0.217 | 0.243 | 0.250 |

### Reinforcement Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.033 | 0.033 | 0.036 | 0.037 |
| `conflict_penalty` | 0.158 | 0.156 | 0.171 | 0.176 |
| `entropy_penalty` | 0.333 | 0.343 | 0.376 | 0.382 |
| `persistence_component` | 0.026 | 0.026 | 0.028 | 0.029 |
| `reinforcement_component` | 0.449 | 0.442 | 0.484 | 0.498 |

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
| Reinforcement persistence duration (est.) | 7 | Consecutive identical belief_state at tail |
| Entropy suppression frequency | 0.000 | High conviction with low entropy penalty |
| Conviction saturation frequency | 0.000 | Share of rows with conviction > 0.90 |
| Alignment dominance ratio | 0.389 | Mean alignment share of decomposition mass |
| Mean conviction probability | 0.704 | Central tendency of exported conviction |
| Mean entropy penalty | 0.716 | Belief-state entropy observability |
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
  "probabilistic_rows_analyzed": 6,
  "reinforcement_rows_analyzed": 7,
  "probabilistic_component_distribution": {
    "alignment_component": {
      "mean_share": 0.3886665906799651,
      "median_share": 0.38830654537770626,
      "p90_share": 0.3904098634480454,
      "max_share": 0.3905660601340693
    },
    "persistence_component": {
      "mean_share": 0.07773331813599302,
      "median_share": 0.07766130907554125,
      "p90_share": 0.07808197268960908,
      "max_share": 0.07811321202681386
    },
    "reinforcement_component": {
      "mean_share": 0.21765713476212456,
      "median_share": 0.2168783474475981,
      "p90_share": 0.24302235272705228,
      "max_share": 0.24996227848580438
    },
    "entropy_penalty": {
      "mean_share": 0.22266297465872567,
      "median_share": 0.22543360952403507,
      "p90_share": 0.24635652556976376,
      "max_share": 0.2507129598169186
    },
    "conflict_penalty": {
      "mean_share": 0.09327998176319163,
      "median_share": 0.09319357089064953,
      "p90_share": 0.09369836722753092,
      "max_share": 0.09373585443217665
    }
  },
  "reinforcement_component_distribution": {
    "alignment_component": {
      "mean_share": 0.03300242357139891,
      "median_share": 0.03252303927315562,
      "p90_share": 0.03558048609577071,
      "max_share": 0.036639556118876475
    },
    "persistence_component": {
      "mean_share": 0.02640193885711913,
      "median_share": 0.026018431418524498,
      "p90_share": 0.028464388876616575,
      "max_share": 0.029311644895101182
    },
    "reinforcement_component": {
      "mean_share": 0.4488329605710253,
      "median_share": 0.44231333411491647,
      "p90_share": 0.48389461090248176,
      "max_share": 0.49829796321672015
    },
    "entropy_penalty": {
      "mean_share": 0.3333510438577419,
      "median_share": 0.3430346066822564,
      "p90_share": 0.375754906515524,
      "max_share": 0.38158148818208154
    },
    "conflict_penalty": {
      "mean_share": 0.1584116331427148,
      "median_share": 0.156110588511147,
      "p90_share": 0.17078633325969947,
      "max_share": 0.1758698693706071
    }
  },
  "probabilistic_dominant_component_frequency": {
    "alignment_component": 1.0
  },
  "reinforcement_dominant_component_frequency": {
    "reinforcement_component": 1.0
  },
  "reinforcement_persistence_duration_estimate": 7,
  "entropy_suppression_frequency": 0.0,
  "conviction_saturation_frequency": 0.0,
  "alignment_dominance_ratio": 0.3886665906799651,
  "high_conviction_state_count": 0,
  "mean_conviction_probability": 0.7043749999999999,
  "mean_entropy_penalty": 0.7161603213110759,
  "mean_conflict_penalty_probabilistic": 0.30000000000000004
}
```

---

*Regenerate:* `venv/bin/python3 conviction_realism_audit.py`
