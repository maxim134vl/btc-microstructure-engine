# Mirror Archive Manifest — Phase 4B

**Archived:** 2026-05-27  
**Source path:** `btc-microstructure-engine/` (repository root)  
**Archive path:** `archive_removed/btc-microstructure-engine-mirror/`  
**Phase tag:** `phase-4b-normalization-hardening`

---

## Lineage

| Item | Detail |
|------|--------|
| Original role | Deprecated duplicate runtime tree with separate `.git` config |
| Canonical replacement | `./run.sh` → `run.py` → `src/btc_ml/runtime/pipeline.py` |
| Deprecation marker | `DEPRECATED.md` (preserved inside archive) |
| Active imports | **None** — verified by `scripts/final_repo_audit.py` |

---

## Contents Summary

- ~509 files including legacy engines, research scripts, monitoring deploy stubs
- Separate orchestrator: `runtime/run_canonical_pipeline.py` (non-canonical geometry pipeline)
- Duplicate copies of root engines (pre-4A mirror state)
- Historical `.git/` metadata (read-only archive — do not use as submodule)

---

## Archive Policy

1. **Do not import** from this tree in active runtime code.
2. **Do not edit** archived files — extract to canonical tree if revival is needed.
3. **Do not delete** without explicit platform governance review.
4. Reference for historical diff only; behavioral semantics are frozen in canonical root engines.

---

## Related Archives

| Path | Contents |
|------|----------|
| `archive_removed/backups/` | 12 `*_backup*.py` engine snapshots (Phase 4A) |
| `archive_removed/snapshots/` | Inventory snapshots (when populated) |

---

*See: `docs/LEGACY_DEPRECATION_PLAN.md`, `docs/PARQUET_STORAGE_TOPOLOGY.md`*
