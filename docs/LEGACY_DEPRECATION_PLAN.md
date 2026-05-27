# Legacy Deprecation Plan

**Phase:** 4B  
**Goal:** Single operational runtime path

---

## Deprecated Entrypoints

| File | Status | Replacement |
|------|--------|-------------|
| `master_auction_runtime_v1.py` | Thin shim → `run_forever()` | `./run.sh` |
| `autonomous_runtime_v1.py` | Exit + warning | `./run.sh` |
| `autonomous_runtime_v2.py` | Exit + warning | `./run.sh` |
| `behavioral_runtime_orchestrator_v1.py` | Exit + warning | `./run.sh` |

All shims emit `DeprecationWarning` on invocation.

---

## Deprecated Mirror Tree

| Path | Action |
|------|--------|
| `btc-microstructure-engine/` | **Archived** → `archive_removed/btc-microstructure-engine-mirror/` |

Manifest: `archive_removed/mirror_archive_manifest.md`

---

## Deprecated Parquet Paths

| Legacy | Canonical |
|--------|-----------|
| `{repo_root}/*.parquet` | `data/<category>/*.parquet` |
| `datasets/live/latest.parquet` | `data/live/live_market_feed.parquet` (+ mirror sync) |

Registry handles migration transparently via `storage/path_registry.py`.

---

## Shim Import Map (Temporary)

| Root module | Package shim |
|-------------|--------------|
| `parquet_utils`, `state_manager_v1` | `btc_ml.storage` |
| `config/*` | `btc_ml.config` |
| Ontology / calibration modules | `btc_ml.ontology`, `btc_ml.calibration` |

Root modules remain authoritative; shims re-export for gradual normalization.

---

## Removal Timeline (Post-4B)

1. **Phase 5+:** Remove root parquet after full `data/` migration confirmed
2. **Phase 5+:** Collapse root engine imports into `src/btc_ml/services/`
3. **Future:** Remove legacy shims after one release cycle with zero shim usage

---

## Non-Goals

- No ontology changes during deprecation
- No execution logic changes
- No autonomous runtime revival
