# REGIME TRANSITION MODEL

**Status:** Phase 2A — probabilistic regime segmentation  
**Updated:** 2026-05-27  
**Module:** `regime_segmentation.py`

---

## 1. Purpose

Provide a **probabilistic cross-regime classification layer** for robustness analysis without rewriting auction/climax ontology or changing existing threshold gates.

---

## 2. Regime States

| Regime | Inference signals (soft scoring) |
|--------|----------------------------------|
| `TREND_EXPANSION` | HIGH_CONVICTION_AUCTION, elevated raw conviction |
| `TREND_EXHAUSTION` | LOCAL_EXHAUSTION synthesis, structural regime |
| `COMPRESSION` | Low absorption/distribution spread, low volatility |
| `VOLATILITY_EXPANSION` | Rising spread / spread volatility |
| `VOLATILITY_COLLAPSE` | Falling spread, low volatility |
| `LIQUIDATION_EVENT` | LOWER_CAPITULATION, climax trigger events |
| `ABSORPTION_RECOVERY` | ABSORPTION_REGIME, LOWER_ABSORPTION |
| `BALANCED_AUCTION` | High entropy + conflict, uncertain auction regime |

Each regime receives a prior + additive evidence score. Scores normalize to a probability vector.

---

## 3. Exports

| Field | Description |
|-------|-------------|
| `regime_state` | Highest-probability regime label |
| `regime_confidence` | Normalized probability of selected regime |
| `regime_transition_probability` | Recent transition rate + current shift signal |
| `regime_probability_vector` | Pipe-delimited full distribution |

---

## 4. Design Constraints

- **Probabilistic:** no hard deterministic switching
- **Observability-only:** does not replace `auction_regime` gates
- **No ontology rewrite:** uses existing synthesis, location, volume, candle fields

---

## 5. Entropy Transition Types

Tracked in `calibration_stability.py`:

| Transition | Condition |
|------------|-----------|
| `LOW_TO_HIGH_ENTROPY` | Entropy delta > 0.08 |
| `COMPRESSION_TO_EXPANSION` | Compression regime + entropy rise |
| `EXHAUSTION_TO_REVERSAL` | LOCAL_EXHAUSTION + entropy rise |
| `LIQUIDATION_TO_ABSORPTION` | Liquidation regime + absorption probability |
| `STABLE_ENTROPY` | default |

---

## 6. Contradiction Persistence

| Metric | Meaning |
|--------|---------|
| `contradiction_duration` | Consecutive elevated conflict density |
| `contradiction_escalation_score` | Conflict density delta |
| `unresolved_contradiction_score` | Weighted unresolved contradiction load |

---

## 7. Walk-Forward Robustness

`calibration_stability.walk_forward_epochs()` implements:

```text
train_window (200) → freeze baseline → forward_observation (50)
```

Exports per runtime row (latest epoch):

- `walk_forward_epoch`
- `calibration_stability_score`
- `regime_drift_score`

---

## 8. Verification & Replay

```bash
venv/bin/python3 scripts/verify_phase2a_robustness.py
venv/bin/python3 scripts/replay_validation/cross_regime/replay_runner.py
venv/bin/python3 cross_regime_calibration_analysis.py
```

---

*See also: `docs/CROSS_REGIME_CALIBRATION_ANALYSIS.md`, `docs/CALIBRATION_DRIFT_MODEL.md`*
