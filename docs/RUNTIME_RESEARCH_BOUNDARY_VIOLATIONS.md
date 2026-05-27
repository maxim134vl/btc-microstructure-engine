# RUNTIME / RESEARCH BOUNDARY VIOLATIONS

**Status:** Flagged — requires fix before Stage 2 production wiring  
**Updated:** 2026-05-26  
**Policy:** Research patterns must not silently affect live runtime  
**Behavioral thresholds:** Out of scope — these are wiring / data-boundary issues only

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Live runtime produces wrong or stale cognition |
| **HIGH** | Lookahead or research-only data in detection path |
| **MEDIUM** | Missing wiring — runtime step depends on manual batch |
| **LOW** | Documentation / path inconsistency |

---

## Resolved in Phase 0A (2026-05-26)

| ID | Resolution |
|----|------------|
| **V-001** | `stage2_cognition_runtime_v1.py` added to master loop; writes `multi_timeframe_synthesis.parquet` + `runtime_cognition_memory.parquet` |
| **V-002** | Canonical feed path `live_market_feed.parquet` via `live_feed_paths.py`; legacy mirror kept |
| **V-011** | `process_auction_climax` uses passed `dataset`; STATE only in standalone `run()` |

---

## CRITICAL (open)

| Field | Detail |
|-------|--------|
| **Location** | `runtime_cognition_engine_v1.py` |
| **Issue** | If `alignment_score` missing from cognition parquet, silently merges from `multi_timeframe_synthesis.parquet` with default `0.25` |
| **Impact** | Runtime appears healthy with synthetic defaults |
| **Fix** | Fail loud if required columns missing in production mode; keep fallback for research mode only |

---

## HIGH — Lookahead / Research Leakage

### V-010 — `future_return_3` in stopping volume detection

| Field | Detail |
|-------|--------|
| **Location** | `auction_climax_engine_v1.py` → `stopping_volume_condition` |
| **Issue** | Uses `close.shift(-3)` — unknowable at bar close in live trading |
| **Impact** | Stopping volume events cannot be reproduced live; backtest inflation |
| **Fix** | Gate behind `RESEARCH_MODE` env flag OR replace with live-safe proxy (separate domain review) |
| **Status** | **Deferred** — user requested no threshold/logic changes now |

---

### V-011 — RESOLVED (Phase 0A)

`process_auction_climax(dataset, timeframe)` now uses the passed dataset. Standalone `run()` still loads from `STATE` for dev entry.

---

### V-003 — `runtime_cognition_engine` fallback masks missing data

| Field | Detail |
|-------|--------|
| **Location** | `research_dataset_builder_v1.py`, `multi_timeframe_dataset_builder.py` |
| **Issue** | Top-level execution on import — not safe as library module |
| **Impact** | Import triggers full batch pipeline |
| **Fix** | Wrap in `main()` + `if __name__` during migration Phase 6 |

---

## MEDIUM — Wiring Gaps

### V-020 — Climax engine has no parquet persistence

| Field | Detail |
|-------|--------|
| **Location** | `auction_climax_engine_v1.py` |
| **Issue** | Returns in-memory dict only — no memory parquet written |
| **Impact** | Downstream cannot consume climax unless via batch builder |
| **Fix** | Add optional write to `auction_climax_memory.parquet` — schema design needed |

---

### V-021 — Stage 2 not in `runtime_dependency_map.py`

| Field | Detail |
|-------|--------|
| **Location** | `runtime_dependency_map.py` |
| **Issue** | No guard for `multi_timeframe_synthesis.parquet` / `runtime_cognition_memory.parquet` |
| **Impact** | Step 11 runs even when Stage 2 batch failed |
| **Fix** | Add dependency entries when Stage 2 wired |

---

### V-022 — Cross-pipeline parquet bleed

| Field | Detail |
|-------|--------|
| **Location** | `volume_response_engine_v1.py`, `behavioral_sequence_memory_v1.py` |
| **Issue** | Read `candle_geometry_v2_memory.parquet`, `volume_localization_v2_memory.parquet` from microstructure v2 pipeline |
| **Impact** | Auction runtime depends on files produced by deprecated `autonomous_runtime_v2` path |
| **Fix** | Document as required inputs OR produce within auction pipeline — architecture decision |

---

### V-023 — `microstructure_candle_engine_v1` reads static `btc_15m.parquet`

| Field | Detail |
|-------|--------|
| **Location** | `microstructure_candle_engine_v1.py` (step 6) |
| **Issue** | Static historical file, not live feed |
| **Impact** | Step 6 may process stale data while rest of pipeline is live |
| **Fix** | Repoint to live candle source or mark step deprecated |

---

### V-024 — `probabilistic_auction_engine` conviction can exceed 1.0

| Field | Detail |
|-------|--------|
| **Location** | `probabilistic_auction_engine_v1.py` |
| **Issue** | Observed output `CONVICTION PROBABILITY: 1.25` |
| **Impact** | May be intentional scaling — needs domain confirmation |
| **Fix** | Deferred — domain review |

---

## LOW — Documentation / Path

### V-030 — Conflicting runtime documentation

| Docs | Claims |
|------|--------|
| `docs/SYSTEM_MAP.md` | master auction primary |
| `README_RUNTIME.md` | run_canonical_pipeline primary |
| `docker-compose.yml` (mirror) | autonomous_runtime_v2 primary |

**Fix:** Update all to reference `docs/CANONICAL_RUNTIME_MAP.md`

---

### V-031 — `multi_timeframe_synthesis_engine.run()` reads research dataset

| Field | Detail |
|-------|--------|
| **Location** | `multi_timeframe_synthesis_engine.py` → `run()` |
| **Issue** | Standalone entry reads `research_master_dataset.parquet` — research artifact |
| **Impact** | Standalone test != production path |
| **Fix** | Document as dev entry only |

---

## Summary Matrix

| ID | Severity | Category | Block Stage 2 wiring? |
|----|----------|----------|----------------------|
| V-001 | CRITICAL | Missing batch in loop | **Yes** |
| V-002 | CRITICAL | Feed path split | **Yes** |
| V-003 | CRITICAL | Silent fallback | Recommended |
| V-010 | HIGH | Lookahead | No (defer) |
| V-011 | HIGH | Ignored dataset param | **Yes** for MTF |
| V-012 | HIGH | Import side effects | No |
| V-020 | MEDIUM | No climax parquet | No |
| V-021 | MEDIUM | Missing guard | After wiring |
| V-022 | MEDIUM | Cross-pipeline deps | Review |
| V-023 | MEDIUM | Static input | Review |
| V-024 | MEDIUM | Math overflow | Defer |
| V-030 | LOW | Docs | No |
| V-031 | LOW | Dev entry | No |

---

## Recommended Fix Order (orchestration only)

1. **V-002** — Align feed output path (config)
2. **V-001** — Wire Stage 2 batch before cognition step
3. **V-011** — Use passed dataset in climax (API fix)
4. **V-003** — Strict mode for production cognition load
5. **V-021** — Extend dependency guard

**Do not touch:** V-010, V-024 (domain/threshold review)

---

*See also: `docs/CANONICAL_RUNTIME_MAP.md`, `docs/PARQUET_DEPENDENCY_MAP.md`, `TODO_REVIEW.md`*
