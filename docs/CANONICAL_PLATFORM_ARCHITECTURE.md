# CANONICAL PLATFORM ARCHITECTURE

**Status:** Phase 4A — structural consolidation  
**Updated:** 2026-05-27

---

## 1. Platform Layers

```text
run.py / run.sh
  └── src/btc_ml/runtime/pipeline.py     (17-step canonical loop)
        ├── structure engines (subprocess)
        ├── stage2 cognition (in-process)
        ├── cognition / reinforcement / probabilistic (in-process)
        └── meta / decay / transition

config/                                 (unified feature flags)
artifacts/ | reports/ | replays/        (generated output separation)
scripts/verify_phase*.py                (phase verification chain)
scripts/replay_validation/              (replay infrastructure)
```

---

## 2. Package Layout (`src/btc_ml/`)

| Package | Role | Migration status |
|---------|------|------------------|
| `runtime/` | Canonical pipeline | Extracted (Phase 4A) |
| `ontology/` | Shim → root ontology modules | Incremental |
| `calibration/` | Shim → calibration modules | Incremental |
| `diagnostics/` | Shim → lineage, adversarial, stabilization | Incremental |
| `resilience/` | Shim → drift, adversarial stability | Incremental |
| `storage/` | Shim → parquet utils, state manager | Incremental |
| `config/` | Shim → unified `config/` | Incremental |

Root modules remain authoritative during transition; shims preserve backward compatibility.

---

## 3. Operational Principles

- **Move, don't rewrite** — no ontology or probabilistic logic changes
- **Warning-first diagnostics** — no autonomous self-modification
- **Single config truth** — `config/` re-exports all flag modules
- **Artifact separation** — generated outputs target `artifacts/`, `reports/`, `replays/`

---

## 4. Verification

```bash
venv/bin/python3 scripts/verify_phase4a_consolidation.py
venv/bin/python3 scripts/final_repo_audit.py
```

---

*See also: `docs/RUNTIME_FREEZE_CANDIDATE.md`, `docs/MIGRATION_PLAN_SRC_BTC_ML.md`*
