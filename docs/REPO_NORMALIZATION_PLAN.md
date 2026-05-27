# REPO NORMALIZATION PLAN

**Status:** Phase 4A — in progress  
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

## 2. Pending (Post-4A)

| Item | Action |
|------|--------|
| `btc-microstructure-engine/` mirror | Archive entire tree → `archive_removed/btc-microstructure-engine-mirror/` |
| Inventory snapshots | Move `python_files.txt`, `parquet_inventory.txt`, etc. → `archive_removed/snapshots/` |
| Generated audit docs | Relocate to `reports/` or exclude from commits |
| Root `.parquet` files | Migrate to `data/` (Migration Phase 9) |
| `master_auction_runtime_v1.py` | Convert to thin shim after pipeline validation |
| Deprecated orchestrators | Archive `autonomous_runtime_v*`, `behavioral_runtime_loop_v1` |

---

## 3. Non-Goals (Frozen)

- Ontology expansion or redesign
- Threshold recalibration
- Execution / PnL optimization
- Autonomous learning

---

*See also: `docs/DUPLICATE_RESOLUTION_PLAN.md`*
