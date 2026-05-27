# CONVICTION REALISM AUDIT

**Generated:** 2026-05-27T10:08:13.916064+00:00  
**Phase:** 1A — Probabilistic Calibration Diagnostics  
**Scope:** Observability only — no calibration changes applied

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **11**
- Reinforcement rows analyzed: **12**
- HIGH_CONVICTION belief rows: **0**

## 2. Component Contribution Distribution

### Probabilistic Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.395 | 0.391 | 0.407 | 0.414 |
| `conflict_penalty` | 0.095 | 0.094 | 0.098 | 0.099 |
| `entropy_penalty` | 0.242 | 0.251 | 0.270 | 0.272 |
| `persistence_component` | 0.079 | 0.078 | 0.081 | 0.083 |
| `reinforcement_component` | 0.189 | 0.187 | 0.236 | 0.250 |

### Reinforcement Memory

| Component | Mean Share | Median Share | P90 Share | Max Share |
|-----------|------------|--------------|-----------|-----------|
| `alignment_component` | 0.031 | 0.031 | 0.035 | 0.037 |
| `conflict_penalty` | 0.152 | 0.148 | 0.167 | 0.176 |
| `entropy_penalty` | 0.359 | 0.377 | 0.398 | 0.398 |
| `persistence_component` | 0.025 | 0.025 | 0.028 | 0.029 |
| `reinforcement_component` | 0.432 | 0.420 | 0.472 | 0.498 |

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
| Reinforcement persistence duration (est.) | 12 | Consecutive identical belief_state at tail |
| Entropy suppression frequency | 0.000 | High conviction with low entropy penalty |
| Conviction saturation frequency | 0.000 | Share of rows with conviction > 0.90 |
| Alignment dominance ratio | 0.395 | Mean alignment share of decomposition mass |
| Mean conviction probability | 0.587 | Central tendency of exported conviction |
| Mean entropy penalty | 0.766 | Belief-state entropy observability |
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
  "probabilistic_rows_analyzed": 11,
  "reinforcement_rows_analyzed": 12,
  "probabilistic_component_distribution": {
    "alignment_component": {
      "mean_share": 0.3949523181109923,
      "median_share": 0.3905660601340693,
      "p90_share": 0.40716237855346354,
      "max_share": 0.4139114399064609
    },
    "persistence_component": {
      "mean_share": 0.07899046362219844,
      "median_share": 0.07811321202681386,
      "p90_share": 0.0814324757106927,
      "max_share": 0.08278228798129218
    },
    "reinforcement_component": {
      "mean_share": 0.18882452895334365,
      "median_share": 0.1873217600457703,
      "p90_share": 0.23608242696830017,
      "max_share": 0.24996227848580438
    },
    "entropy_penalty": {
      "mean_share": 0.24244413296682749,
      "median_share": 0.2507129598169186,
      "p90_share": 0.2703650176321932,
      "max_share": 0.271515865764629
    },
    "conflict_penalty": {
      "mean_share": 0.09478855634663817,
      "median_share": 0.09373585443217665,
      "p90_share": 0.09771897085283127,
      "max_share": 0.09933874557755062
    }
  },
  "reinforcement_component_distribution": {
    "alignment_component": {
      "mean_share": 0.03137323026854765,
      "median_share": 0.030855148343566806,
      "p90_share": 0.0347418303300933,
      "max_share": 0.036639556118876475
    },
    "persistence_component": {
      "mean_share": 0.025398610150670357,
      "median_share": 0.02468411867485345,
      "p90_share": 0.027793464264074644,
      "max_share": 0.029311644895101182
    },
    "reinforcement_component": {
      "mean_share": 0.4317763725613961,
      "median_share": 0.4196300174725086,
      "p90_share": 0.47248889248926895,
      "max_share": 0.49829796321672015
    },
    "entropy_penalty": {
      "mean_share": 0.35906012611536364,
      "median_share": 0.3767260034599503,
      "p90_share": 0.39752747430589613,
      "max_share": 0.39844799865636976
    },
    "conflict_penalty": {
      "mean_share": 0.15239166090402215,
      "median_share": 0.1481047120491207,
      "p90_share": 0.16676078558444787,
      "max_share": 0.1758698693706071
    }
  },
  "probabilistic_dominant_component_frequency": {
    "alignment_component": 1.0
  },
  "reinforcement_dominant_component_frequency": {
    "reinforcement_component": 1.0
  },
  "reinforcement_persistence_duration_estimate": 12,
  "entropy_suppression_frequency": 0.0,
  "conviction_saturation_frequency": 0.0,
  "alignment_dominance_ratio": 0.3949523181109923,
  "high_conviction_state_count": 0,
  "mean_conviction_probability": 0.5874128631418352,
  "mean_entropy_penalty": 0.7663930193658263,
  "mean_conflict_penalty_probabilistic": 0.3
}
```

---

*Regenerate:* `venv/bin/python3 conviction_realism_audit.py`
