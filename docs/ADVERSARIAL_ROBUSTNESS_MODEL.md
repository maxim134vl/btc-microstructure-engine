# ADVERSARIAL ROBUSTNESS MODEL

**Status:** Phase 2B — resilience engineering  
**Updated:** 2026-05-27  
**Modules:** `synthetic_stress_engine.py`, `adversarial_diagnostics.py`

---

## 1. Purpose

Stress-test probabilistic discipline under unstable and adversarial conditions without modifying behavioral ontology, threshold gates, execution, or portfolio logic.

---

## 2. Synthetic Stress Engine

**Module:** `synthetic_stress_engine.py`

| Scenario | Simulated condition |
|----------|-------------------|
| `VOLATILITY_SPIKE` | Entropy + transition shock |
| `FAKE_BREAKOUT` | Conviction/reinforcement spike with rising entropy |
| `LIQUIDITY_VACUUM` | Collapsed absorption/distribution |
| `DELAYED_CONTINUATION` | Weak persistence with delayed conviction |
| `FRAGMENTED_AUCTION` | Contradiction flood |
| `CONTRADICTION_FLOOD` | Conflict density escalation |
| `ENTROPY_SHOCK` | Abrupt entropy rise |
| `ABRUPT_REGIME_FLIP` | Forced regime transition |
| `UNSTABLE_ABSORPTION` | Absorption without persistence |
| `RECURSIVE_REINFORCEMENT_TRAP` | Runaway reinforcement recurrence |

### Requirements met

- Reproducible via `STRESS_ENGINE_SEED`
- Seedable replay across scenarios
- No ontology rewrite
- No execution logic

---

## 3. Feature Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `ENABLE_ADVERSARIAL_DIAGNOSTICS` | `false` | Master adversarial gate |
| `ENABLE_STRESS_SENSITIVITY` | `false` | Run stress scenario sensitivity |
| `STRESS_ENGINE_SEED` | `42` | Reproducible stress replay |
| `FRAGILITY_WARNING_THRESHOLD` | `0.45` | Warning-only alert threshold |

---

## 4. Runtime Integration

When `ENABLE_ADVERSARIAL_DIAGNOSTICS=false` (default):

- Exports present with neutral values
- Runtime conviction path unchanged
- Backward compatible with Phase 2A

When enabled:

- Failure-mode, instability, survival, and resilience exports populated
- Warning-only logs for elevated fragility
- No hard runtime interruption

---

## 5. Verification & Replay

```bash
venv/bin/python3 scripts/verify_phase2b_adversarial.py
venv/bin/python3 scripts/replay_validation/adversarial/replay_runner.py
```

---

## 6. Non-Goals

- No PnL optimization
- No execution optimization
- No deployment scaling
- No ontology redesign

---

*See also: `docs/FAILURE_MODE_ANALYSIS.md`, `docs/INSTABILITY_PROPAGATION_MODEL.md`, `docs/REGIME_TRANSITION_SURVIVAL.md`*
