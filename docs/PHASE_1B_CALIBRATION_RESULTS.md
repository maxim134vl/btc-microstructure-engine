# PHASE 1B CALIBRATION RESULTS

**Generated:** 2026-05-27T10:08:30.197556+00:00  
**Phase:** 1B — Controlled Probabilistic Discipline  
**Default runtime:** discipline flags OFF (backward compatible)

---

## 1. Comparison Summary

| Metric | Discipline OFF | Discipline ON | Delta |
|--------|----------------|---------------|-------|
| Mean conviction | 0.9503 | 0.6734 | -0.2769 |
| Saturation frequency (>0.90) | 0.900 | 0.000 | -0.900 |
| Mean saturation reduction | -0.9000 | -0.3729 | 0.5271 |
| Entropy interaction (mean) | 0.0000 | 0.0006 | 0.0006 |
| Reinforcement stability proxy | 1.2658 | 1.0147 | -0.2511 |

## 2. Discipline ON Detail

- Rows compared: **100**
- Mean raw vs disciplined divergence: **0.1859**
- Max divergence: **0.2575**

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
  "mean_raw_conviction": 0.5031249999999999,
  "mean_disciplined_conviction": 0.9503125000000001,
  "mean_divergence": 0.0,
  "max_divergence": 0.0,
  "saturation_frequency_before": 0.0,
  "saturation_frequency_after": 0.9,
  "mean_saturation_reduction": -0.8999999999999999,
  "entropy_suppression_effectiveness": 0.0,
  "reinforcement_stability_proxy": 1.2657945891605853
}
```

### Discipline ON

```json
{
  "rows_compared": 100,
  "mean_raw_conviction": 0.5031249999999999,
  "mean_disciplined_conviction": 0.6733854374190744,
  "mean_divergence": 0.1858664869027587,
  "max_divergence": 0.2575409605848294,
  "saturation_frequency_before": 0.0,
  "saturation_frequency_after": 0.0,
  "mean_saturation_reduction": -0.37294417221870063,
  "entropy_suppression_effectiveness": 0.0006000000000000005,
  "reinforcement_stability_proxy": 1.0146523160544356
}
```

---

*Regenerate:* `venv/bin/python3 phase_1b_calibration_results.py`
