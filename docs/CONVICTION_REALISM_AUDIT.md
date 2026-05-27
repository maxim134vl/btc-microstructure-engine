# CONVICTION REALISM AUDIT

**Generated:** 2026-05-27T11:51:26.131199+00:00  
**Phase:** 1A — Probabilistic Calibration Diagnostics  
**Scope:** Observability only — no calibration changes applied

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **142**
- Reinforcement rows analyzed: **100**
- HIGH_CONVICTION belief rows: **0**

## 2. Component Contribution Distribution

### Probabilistic Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.665 | 0.694 | 0.694 | 0.781 |
| `conflict_penalty` | 0.148 | 0.167 | 0.167 | 0.167 |
| `entropy_penalty` | 0.034 | 0.000 | 0.219 | 0.272 |
| `persistence_component` | 0.133 | 0.139 | 0.139 | 0.156 |
| `reinforcement_component` | 0.019 | 0.000 | 0.086 | 0.250 |

### Reinforcement Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.050 | 0.050 | 0.050 | 0.050 |
| `conflict_penalty` | 0.221 | 0.238 | 0.238 | 0.238 |
| `entropy_penalty` | 0.000 | 0.000 | 0.000 | 0.000 |
| `persistence_component` | 0.041 | 0.040 | 0.047 | 0.047 |
| `reinforcement_component` | 0.689 | 0.673 | 0.807 | 0.807 |

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
| Reinforcement persistence duration (est.) | 100 | Consecutive identical belief_state at tail |
| Entropy suppression frequency | 0.000 | High conviction with low entropy penalty |
| Conviction saturation frequency | 0.000 | Share of rows with conviction > 0.90 |
| Alignment dominance ratio | 0.665 | Mean alignment share of decomposition mass |
| Mean conviction probability | 0.067 | Central tendency of exported conviction |
| Mean entropy penalty | 0.100 | Belief-state entropy observability |
| Mean conflict penalty (probabilistic) | 0.282 | Conflict signal propagated from reinforcement |

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
  "probabilistic_rows_analyzed": 142,
  "reinforcement_rows_analyzed": 100,
  "probabilistic_component_distribution": {
    "alignment_component": {
      "mean_share": 0.6652636424262256,
      "median_share": 0.6944444444444444,
      "p90_share": 0.6944444444444444,
      "max_share": 0.78125
    },
    "persistence_component": {
      "mean_share": 0.13305272848524513,
      "median_share": 0.1388888888888889,
      "p90_share": 0.1388888888888889,
      "max_share": 0.15625
    },
    "reinforcement_component": {
      "mean_share": 0.01925942480502089,
      "median_share": 0.0,
      "p90_share": 0.08612976259424777,
      "max_share": 0.24996227848580438
    },
    "entropy_penalty": {
      "mean_share": 0.034204592073045326,
      "median_share": 0.0,
      "p90_share": 0.21897241101194095,
      "max_share": 0.271515865764629
    },
    "conflict_penalty": {
      "mean_share": 0.14821961221046315,
      "median_share": 0.16666666666666669,
      "p90_share": 0.16666666666666669,
      "max_share": 0.16666666666666669
    }
  },
  "reinforcement_component_distribution": {
    "alignment_component": {
      "mean_share": 0.04961776889855157,
      "median_share": 0.0495049504950495,
      "p90_share": 0.05044510385756676,
      "max_share": 0.05044510385756676
    },
    "persistence_component": {
      "mean_share": 0.04054881452536944,
      "median_share": 0.0396039603960396,
      "p90_share": 0.04747774480712166,
      "max_share": 0.04747774480712166
    },
    "reinforcement_component": {
      "mean_share": 0.6893298469312805,
      "median_share": 0.6732673267326732,
      "p90_share": 0.8071216617210683,
      "max_share": 0.8071216617210683
    },
    "entropy_penalty": {
      "mean_share": 0.0,
      "median_share": 0.0,
      "p90_share": 0.0,
      "max_share": 0.0
    },
    "conflict_penalty": {
      "mean_share": 0.2205035696447983,
      "median_share": 0.2376237623762376,
      "p90_share": 0.2376237623762376,
      "max_share": 0.2376237623762376
    }
  },
  "probabilistic_dominant_component_frequency": {
    "alignment_component": 1.0
  },
  "reinforcement_dominant_component_frequency": {
    "reinforcement_component": 1.0
  },
  "reinforcement_persistence_duration_estimate": 100,
  "entropy_suppression_frequency": 0.0,
  "conviction_saturation_frequency": 0.0,
  "alignment_dominance_ratio": 0.6652636424262256,
  "high_conviction_state_count": 0,
  "mean_conviction_probability": 0.06676663700254089,
  "mean_entropy_penalty": 0.10001690583694746,
  "mean_conflict_penalty_probabilistic": 0.28169014084507055
}
```

---

*Regenerate:* `venv/bin/python3 conviction_realism_audit.py`
