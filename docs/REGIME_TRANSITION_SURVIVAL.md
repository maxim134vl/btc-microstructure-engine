# REGIME TRANSITION SURVIVAL

**Status:** Phase 2B — transition survival analysis  
**Updated:** 2026-05-27  
**Module:** `regime_transition_survival.py`

---

## 1. Purpose

Measure whether disciplined cognition survives critical regime transitions.

---

## 2. Tracked Transitions

| From | To |
|------|-----|
| `TREND_EXPANSION` | `TREND_EXHAUSTION` |
| `COMPRESSION` | `VOLATILITY_EXPANSION` |
| `LIQUIDATION_EVENT` | `ABSORPTION_RECOVERY` |
| `BALANCED_AUCTION` | `TREND_EXPANSION` |

---

## 3. Survival Metrics

| Field | Meaning |
|-------|---------|
| `transition_pair` | Observed from→to regime pair |
| `transition_survival_score` | Survival quality (1.0 = stable) |
| `transition_conviction_lag` | Conviction adaptation lag |
| `transition_reinforcement_destabilization` | Reinforcement instability during transition |
| `transition_contradiction_escalation` | Contradiction rise during transition |
| `transition_entropy_sensitivity` | Entropy shock sensitivity |

---

## 4. Score Interpretation

`transition_survival_score` penalizes:

- High conviction adaptation lag
- Reinforcement destabilization
- Contradiction escalation
- Entropy sensitivity spikes

Non-tracked transitions receive a neutral survival baseline (≥ 0.75).

---

## 5. Replay

```bash
venv/bin/python3 scripts/replay_validation/adversarial/regime_flip_replay.py
venv/bin/python3 scripts/replay_validation/cross_regime/regime_transition_replay.py
```

---

*See also: `docs/REGIME_TRANSITION_MODEL.md`, `docs/ADVERSARIAL_ROBUSTNESS_MODEL.md`*
