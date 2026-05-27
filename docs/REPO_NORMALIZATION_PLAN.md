# REPO NORMALIZATION PLAN

**Status:** Phase 4B — complete  
**Updated:** 2026-05-27

---

## 1. Completed (Phase 4A)

- [x] `src/btc_ml/` package skeleton with shims
- [x] Unified `config/` layer
- [x] Canonical entrypoint `run.py` / `run.sh`
- [x] `pyproject.toml` editable package scaffold
- [x] Backup engines → `archive_removed/backups/` (12 files)
- [x] Artifact directories: `artifacts/`, `reports/`, `replays/`
- [x] Schema validation operational stub (empty engine fix)
- [x] Final validation replay suite
- [x] `scripts/final_repo_audit.py`

---

## 2. Completed (Phase 4B)

- [x] `storage/path_registry.py` — canonical parquet truth
- [x] `data/` layout with legacy migration shims
- [x] `master_auction_runtime_v1.py` → thin deprecation shim
- [x] Legacy orchestrators deprecated with warnings
- [x] Mirror archived → `archive_removed/btc-microstructure-engine-mirror/`
- [x] `runtime_hardening.py` operational gate
- [x] `scripts/bootstrap_runtime.sh` reproducible deploy
- [x] Expanded `scripts/final_repo_audit.py`
- [x] `scripts/verify_phase4b_hardening.py`
- [x] `pyproject.toml` + `requirements-runtime.txt` normalization
- [x] Platform freeze candidate documentation

---

## 3. Remaining (Post-4B)

| Item | Action |
|------|--------|
| Root engine → package migration | `src/btc_ml/services/` |
| Root shim removal | After import normalization |
| Non-pipeline script parquet paths | Gradual registry adoption |
| CI / Makefile / lint | DevOps hardening |

---

## 4. Non-Goals (Frozen)

- Ontology expansion or redesign
- Threshold recalibration
- Execution / PnL optimization
- Autonomous learning

---

*See also: `docs/FINAL_PLATFORM_FREEZE.md`, `docs/LEGACY_DEPRECATION_PLAN.md`*
