# ONTOLOGY STABILIZATION MODEL

**Status:** Phase 3B — post-separation behavioral validation  
**Updated:** 2026-05-27  
**Module:** `ontology_stabilization.py`

---

## 1. Purpose

Validate downstream behavioral stability after Phase 3A absorption/capitulation separation without introducing new ontology classes or modifying execution logic.

---

## 2. Analysis Layers

| Layer | Module | Exports |
|-------|--------|---------|
| Reinforcement | `post_split_reinforcement_analysis.py` | behavior shift, divergence, stability |
| Contradiction | `contradiction_redistribution.py` | redistribution, conflict shift, resolution quality |
| Entropy | `semantic_entropy_evolution.py` | decay rate, compression, persistence, recovery |
| Transitions | `ontology_transition_stability.py` | transition stability, escalation metrics |
| Drift | `ontology_drift_detection.py` | drift score, stability, fragility |
| BUYING audit | `buying_exhaustion_validation.py` | exhaustion quality, upside fragility |
| HAV audit | `hav_semantic_analysis.py` | semantic density, ambiguity score |
| Overlap | `ontology_overlap_matrix.py` | overlap matrix, semantic overlap score |

---

## 3. Feature Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `ENABLE_ONTOLOGY_STABILIZATION` | `true` | Master stabilization gate |
| `STABILIZATION_WARN_ON_DRIFT` | `true` | Warning-only drift alerts |

---

## 4. Verification

```bash
venv/bin/python3 scripts/verify_phase3b_stabilization.py
venv/bin/python3 scripts/replay_validation/stabilization/stabilization_runner.py
```

---

*See related Phase 3B documentation in `docs/`.*
