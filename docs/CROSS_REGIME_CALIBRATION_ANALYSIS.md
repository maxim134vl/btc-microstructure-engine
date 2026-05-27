# CROSS-REGIME CALIBRATION ANALYSIS

**Generated:** 2026-05-27T11:51:23.514985+00:00  
**Phase:** 2A — Cross-Regime Robustness & Calibration Stability  
**Scope:** Robustness engineering — no ontology or threshold changes

---

## 1. Sample Coverage

- Probabilistic rows analyzed: **200**
- Walk-forward epochs: **1**
- Mean calibration stability score: **0.909**

## 2. Conviction & Calibration Metrics by Regime

| Regime | Rows | Mean Conviction | Saturation Freq | Entropy Effectiveness | Conflict Density | Reinforcement Persistence |
|--------|------|-----------------|-----------------|----------------------|------------------|---------------------------|
| `BALANCED_AUCTION` | 8 | 0.302 | 0.000 | 1.000 | 0.400 | 0.300 |
| `TREND_EXHAUSTION` | 125 | 0.002 | 0.000 | 1.000 | 0.250 | 0.002 |

## 3. Unstable Regime Detection

Regimes flagged when saturation frequency > 0.25, entropy effectiveness < 0.50, or mean conflict density > 0.45.

**Unstable regimes:** _None detected on sample._

## 4. Walk-Forward Robustness

| Epoch | Stability Score | Regime Drift | Conviction Drift | Entropy Drift | Reinforcement Drift |
|-------|-----------------|--------------|------------------|---------------|---------------------|
| 0 | 0.909 | 0.061 | 0.045 | 0.101 | 0.060 |

## 5. Interpretation

This report identifies where disciplined cognition remains stable across changing market structure versus where calibration degrades. High regime drift with low stability scores indicates cross-regime fragility requiring further monitoring before any runtime default changes.

## 6. Raw Metrics JSON

```json
{
  "regime_metrics": {
    "TREND_EXHAUSTION": {
      "rows": 125.0,
      "mean_conviction": 0.0019319999999999995,
      "saturation_frequency": 0.0,
      "entropy_suppression_effectiveness": 1.0,
      "mean_conflict_density": 0.2504,
      "reinforcement_persistence": 0.00192
    },
    "BALANCED_AUCTION": {
      "rows": 8.0,
      "mean_conviction": 0.301875,
      "saturation_frequency": 0.0,
      "entropy_suppression_effectiveness": 1.0,
      "mean_conflict_density": 0.4,
      "reinforcement_persistence": 0.3
    }
  },
  "walk_forward_epochs": [
    {
      "walk_forward_epoch": 0,
      "calibration_stability_score": 0.9087605012034414,
      "regime_drift_score": 0.06060606060606058,
      "conviction_drift": 0.044625,
      "entropy_drift": 0.10072624559465632,
      "reinforcement_drift": 0.059574468085106386,
      "contradiction_persistence": 0.25,
      "calibration_degradation": 0.0912394987965586
    }
  ],
  "unstable_regimes": []
}
```

---

*Regenerate:* `venv/bin/python3 cross_regime_calibration_analysis.py`
