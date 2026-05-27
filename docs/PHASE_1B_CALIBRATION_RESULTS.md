# PHASE 1B CALIBRATION RESULTS

**Generated:** 2026-05-27T11:51:31.045415+00:00  
**Phase:** 1B — Controlled Probabilistic Discipline  
**Default runtime:** discipline flags OFF (backward compatible)

---

## 1. Comparison Summary

| Metric | Discipline OFF | Discipline ON | Delta |
|--------|----------------|---------------|-------|
| Mean conviction | 0.0000 | 0.0648 | 0.0648 |
| Saturation frequency (>0.90) | 0.000 | 0.000 | 0.000 |
| Mean saturation reduction | 0.0000 | 0.0000 | 0.0000 |
| Entropy interaction (mean) | 0.0000 | 0.0000 | 0.0000 |
| Reinforcement stability proxy | 0.0000 | 0.0000 | 0.0000 |

## 2. Discipline ON Detail

- Rows compared: **100**
- Mean raw vs disciplined divergence: **-0.0648**
- Max divergence: **-0.0648**

## 3. Rollout Guidance

1. Keep `ENABLE_PROBABILISTIC_DISCIPLINE=false` in production until replay review passes.
2. Enable discipline in replay/staging via environment flags.
3. Set `USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true` only after saturation reduction confirmed.
4. Use `CALIBRATION_MODE=disciplined` before `sigmoid` for conservative rollout.

## 4. Environment Flags

```bash
export ENABLE_PROBABILISTIC_DISCIPLINE=true
export USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true
export CALIBRATION_MODE=disciplined   # raw | disciplined | sigmoid
```

## 5. Raw Metrics JSON

### Discipline OFF

```json
{
  "rows_compared": 100,
  "mean_raw_conviction": 0.0,
  "mean_disciplined_conviction": 0.0,
  "mean_divergence": 0.0,
  "max_divergence": 0.0,
  "saturation_frequency_before": 0.0,
  "saturation_frequency_after": 0.0,
  "mean_saturation_reduction": 0.0,
  "entropy_suppression_effectiveness": 0.0,
  "reinforcement_stability_proxy": 0.0
}
```

### Discipline ON

```json
{
  "rows_compared": 100,
  "mean_raw_conviction": 0.0,
  "mean_disciplined_conviction": 0.06483781792779535,
  "mean_divergence": -0.06483781792779535,
  "max_divergence": -0.06483781792779535,
  "saturation_frequency_before": 0.0,
  "saturation_frequency_after": 0.0,
  "mean_saturation_reduction": 0.0,
  "entropy_suppression_effectiveness": 0.0,
  "reinforcement_stability_proxy": 0.0
}
```

---

*Regenerate:* `venv/bin/python3 phase_1b_calibration_results.py`
