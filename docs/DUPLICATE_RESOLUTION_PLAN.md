# DUPLICATE RESOLUTION PLAN

**Status:** Approved — root canonical, mirror deprecated  
**Updated:** 2026-05-26  
**Scope:** 237 duplicate filenames between root and `btc-microstructure-engine/`  
**Behavioral logic:** No changes — file ownership and deprecation only

---

## 1. Policy

| Rule | Detail |
|------|--------|
| **Canonical** | Repository root (`/Users/fontecrypto/btc-ml/*.py`) |
| **Deprecated** | `btc-microstructure-engine/` — full mirror, no further edits |
| **Diverged files (12)** | Root version wins — no merge review needed |
| **Identical files (225)** | Safe to archive mirror copies after verification |
| **New code** | Only in root (later: `src/btc_ml/`) |

---

## 2. The 12 Diverged Files — Resolution

**Decision:** Root is canonical. Mirror copies marked deprecated.

| # | File | Root | Mirror | Action |
|---|------|-----:|-------:|--------|
| 1 | `state_manager_v1.py` | 96 lines, has `candle_structure` | 74 lines | Archive mirror |
| 2 | `master_auction_runtime_v1.py` | 187 lines, cognition step | 119 lines | Archive mirror |
| 3 | `probabilistic_auction_engine_v1.py` | 497 lines | 323 lines | Archive mirror |
| 4 | `auction_reinforcement_engine_v1.py` | 424 lines | 259 lines | Archive mirror |
| 5 | `auction_convergence_engine_v1.py` | 317 lines | 261 lines | Archive mirror |
| 6 | `volume_response_engine_v1.py` | 988 lines | 937 lines | Archive mirror |
| 7 | `auction_decay_engine_v1.py` | 229 lines | 247 lines | Archive mirror |
| 8 | `auction_synthesis_engine_v1.py` | 325 lines | 305 lines | Archive mirror |
| 9 | `behavioral_sequence_memory_v1.py` | 285 lines | 276 lines | Archive mirror |
| 10 | `candle_structure_engine_v1.py` | 353 lines | 351 lines | Archive mirror |
| 11 | `live_binance_feed_v2.py` | writes `datasets/live/latest.parquet` | writes `live_market_feed.parquet` | Archive mirror; **flag feed path** |
| 12 | `state_transition_engine_v1.py` | 304 lines | 238 lines | Archive mirror |

**No diff merge required.** Root already approved as truth.

---

## 3. Root-Only Modules (No Mirror — Stage 2 Canonical)

These exist **only at root** and define the production direction:

```
auction_climax_engine_v1.py
multi_timeframe_synthesis_engine.py
multi_timeframe_dataset_builder.py
research_dataset_builder_v1.py
runtime_cognition_engine_v1.py
parquet_utils.py
state_guard.py
runtime_config.py
runtime_cache.py
runtime_dependency_map.py
runtime_dependency_guard.py
runtime_state_manager.py
```

**Action:** Move to `src/btc_ml/` in migration — never copy to mirror.

---

## 4. Execution Phases

### Phase A — Freeze mirror (immediate, no file moves)

- [ ] Add `btc-microstructure-engine/DEPRECATED.md` pointing to root
- [ ] Add CI/pre-commit note: reject edits under `btc-microstructure-engine/`
- [ ] Update `README_RUNTIME.md` header: deprecated path

### Phase B — Verify no active imports from mirror (1 day)

```bash
# Run from repo root — cwd must be root for canonical imports
cd /Users/fontecrypto/btc-ml
grep -r "btc-microstructure-engine" --include="*.py" --include="*.yml" --include="*.sh" .
```

- [ ] Confirm Docker/deploy scripts either updated or marked deprecated
- [ ] Confirm no cron/launchd jobs reference mirror path

### Phase C — Archive mirror tree (after Phase B)

```
archive_removed/
└── btc-microstructure-engine-mirror-2026-05-26/
    └── (full copy of btc-microstructure-engine/)
```

- [ ] Move `btc-microstructure-engine/` → `archive_removed/`
- [ ] Leave stub `btc-microstructure-engine/README.md`:

  > This path is deprecated. Canonical code is at repository root and `src/btc_ml/`.

**Risk:** Docker compose in mirror references autonomous v2. **Do not delete** until Docker realigned or removed.

### Phase D — Remove identical duplicates (225 files)

After mirror archived, no action needed on individual files — entire tree moved.

### Phase E — Clean root backups (12 files)

Move to `archive_removed/backups/`:

```
master_auction_runtime_v1_backup.py
master_auction_runtime_v1_backup2.py
live_binance_feed_v2_backup.py
live_binance_feed_backup.py
behavioral_sequence_memory_v1_backup.py
behavioral_sequence_memory_v1_incremental_backup.py
collectors/*_backup.py  (6 files)
```

---

## 5. Inventory Snapshots — Remove from Root

Move to `archive_removed/snapshots/`:

```
project_structure.txt
python_files.txt
python_sizes.txt
top_python_sizes.txt
parquet_inventory.txt
directories_snapshot.txt
```

---

## 6. Verification Checklist (Before Mirror Archive)

| Check | Command / method | Pass? |
|-------|------------------|-------|
| Master runtime starts from root | `venv/bin/python3 master_auction_runtime_v1.py` | Manual |
| Stage 2 batch runs | `venv/bin/python3 research_dataset_builder_v1.py` | Manual |
| No import from mirror | `grep -r btc-microstructure-engine .` | Automated |
| Git tracks mirror separately | Review `git log -- btc-microstructure-engine/` | Manual |
| Parquet paths resolve from root cwd | Run one engine cycle | Manual |

---

## 7. Rollback Plan

If mirror removal breaks something:

1. Restore from `archive_removed/btc-microstructure-engine-mirror-2026-05-26/`
2. Document which script still depended on mirror path
3. Fix import/cwd, re-attempt archive

---

## 8. What NOT to Do

- Do **not** merge mirror diverged files into root (root already canonical)
- Do **not** delete mirror before deploy path audit
- Do **not** change behavioral thresholds during duplicate cleanup
- Do **not** deduplicate by deleting root copies

---

*See also: `docs/MIGRATION_PLAN_SRC_BTC_ML.md`, `docs/CANONICAL_RUNTIME_MAP.md`*
