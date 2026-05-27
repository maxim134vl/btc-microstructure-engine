# CROSS-REGIME CALIBRATION ANALYSIS

**Generated:** 2026-05-27T10:08:09.328079+00:00  
**Phase:** 2A — Cross-Regime Robustness & Calibration Stability  
**Scope:** Robustness engineering — no ontology or threshold changes

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **200**
- Walk-forward epochs: **1**
- Mean calibration stability score: **0.785**

## 2. Conviction & Calibration Metrics by Regime

| Regime | Rows | Mean Conviction | Saturation Freq | Entropy Effectiveness | Conflict Density | Reinforcement Persistence |
|--------|------|-----------------|-----------------|----------------------|------------------|---------------------------|
| `BALANCED_AUCTION` | 1 | 0.443 | 0.000 | 1.000 | 0.400 | 0.440 |

## 3. Unstable Regime Detection

Regimes flagged when saturation frequency > 0.25, entropy effectiveness < 0.50, or mean conflict density > 0.45.

**Unstable regimes:** _None detected on sample._

## 4. Walk-Forward Robustness

| Epoch | Stability Score | Regime Drift | Conviction Drift | Entropy Drift | Reinforcement Drift |
|-------|-----------------|--------------|------------------|---------------|---------------------|
| 0 | 0.785 | 0.500 | 0.141 | 0.077 | 0.200 |

## 5. Interpretation

This report identifies where disciplined cognition remains stable across changing market structure versus where calibration degrades. High regime drift with low stability scores indicates cross-regime fragility requiring further monitoring before any runtime default changes.

## 6. Raw Metrics JSON

```json
{
  "regime_metrics": {
    "BALANCED_AUCTION": {
      "rows": 1.0,
      "mean_conviction": 0.44275,
      "saturation_frequency": 0.0,
      "entropy_suppression_effectiveness": 1.0,
      "mean_conflict_density": 0.4,
      "reinforcement_persistence": 0.44
    }
  },
  "walk_forward_epochs": [
    {
      "walk_forward_epoch": 0,
      "calibration_stability_score": 0.7853619975637526,
      "regime_drift_score": 0.5,
      "conviction_drift": 0.14087499999999997,
      "entropy_drift": 0.07665876218123724,
      "reinforcement_drift": 0.2,
      "contradiction_persistence": 0.4,
      "calibration_degradation": 0.21463800243624742
    }
  ],
  "unstable_regimes": []
}
```

---

*Regenerate:* `venv/bin/python3 cross_regime_calibration_analysis.py`
