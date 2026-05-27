# TODO_REVIEW — Manual Review Required

**Updated:** 2026-05-26 (post architectural decisions)

---

## ✅ RESOLVED — Architecture (2026-05-26)

- [x] **Canonical runtime:** `master_auction_runtime_v1.py`
- [x] **Canonical source tree:** Repository root; `btc-microstructure-engine/` → deprecated mirror
- [x] **Stage 2 scope:** Primary production direction (climax → MTF → cognition → reinforcement → probabilistic → meta)
- [x] **Diverged duplicates (12):** Root versions canonical — archive mirror copies

---

## P0 — Block Stage 2 Production Wiring (orchestration only)

- [x] **V-002 Feed path:** Canonical `live_market_feed.parquet` via `live_feed_paths.py` + legacy mirror
- [x] **V-001 Stage 2 batch:** `stage2_cognition_runtime_v1.py` wired in master loop before cognition load
- [x] **V-011 Climax API:** `process_auction_climax` uses passed `dataset` (STATE only in standalone `run()`)
- [ ] **V-003 Cognition fallback:** Remove silent `alignment_score` default in production mode

See: `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`

---

## P0 — Mirror Deprecation

- [ ] Add `btc-microstructure-engine/DEPRECATED.md` ✅ (this commit)
- [ ] Verify no active deploy scripts reference mirror path
- [ ] Archive mirror to `archive_removed/` (after deploy audit)
- [ ] **Mutation engine in Docker:** `live_mutation_runtime_engine_v1.py` in deprecated mirror compose — do not migrate; ignore

---

## P1 — Domain Logic (DEFERRED — user requested freeze)

Do **not** change during repository refactor:

- [ ] **Climax separation:** SELLING_CLIMAX vs STOPPING_VOLUME cluster merge
- [ ] **`future_return_3`** in stopping volume — research-only gate or live-safe replacement
- [ ] **`conviction_probability`** exceeds 1.0 — domain confirmation

---

## P1 — Security (can automate after migration Phase 2)

- [ ] Replace `os.system()` with `subprocess.run([...])` in orchestrators
- [ ] Re-enable SSL verification in collectors
- [ ] Fix CORS in `monitoring_api_v1.py`

---

## P2 — Cleanup (after mirror archive)

- [ ] Move 12 `*_backup*.py` to `archive_removed/backups/`
- [ ] Move inventory snapshot `.txt` to `archive_removed/snapshots/`
- [ ] Consolidate `initiative_memory_engine_v1–v9`
- [ ] Fix or remove broken `research_lab.py`

---

## P2 — Documentation

- [x] Populate `docs/PARQUET_DEPENDENCY_MAP.md`
- [x] Create `docs/CANONICAL_RUNTIME_MAP.md`
- [x] Create `docs/DUPLICATE_RESOLUTION_PLAN.md`
- [x] Create `docs/MIGRATION_PLAN_SRC_BTC_ML.md`
- [x] Create `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`
- [ ] Mark `README_RUNTIME.md` as deprecated (points to wrong runtime)
- [ ] Add root `README.md`
- [ ] Update `docs/SYSTEM_MAP.md` with Stage 2 section

---

## Migration Phase Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Documentation + audit | ✅ Done |
| 0A | Runtime wiring integrity | ✅ Done |
| 1 | `src/btc_ml/` skeleton | Pending |
| 2 | Infrastructure move | Pending |
| 3 | Service engines move | Pending |
| 4 | Orchestration extract | Pending |
| 5 | Stage 2 wiring | Pending (after P0 fixes) |
| 6 | Research scripts relocate | Pending |
| 7 | Mirror archive | Pending |
| 8 | DevOps (pyproject, Makefile) | Pending |

See: `docs/MIGRATION_PLAN_SRC_BTC_ML.md`

---

*Behavioral calibration changes are explicitly out of scope until post-migration domain review.*
