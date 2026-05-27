# Ontology Density Restoration

**Status:** Diagnostic-driven restoration (post Phase 4B)  
**Architecture reference:** `Full Trading System Architecture Stage1 Stage2 Ru V1.docx` (authoritative — attach to repo when available)  
**Interim references:** `docs/ONTOLOGY_REFINEMENT_MODEL.md`, `docs/EFFORT_RESULT_SEMANTICS.md`, `docs/CANONICAL_RUNTIME_MAP.md`

---

## 1. Executive Summary

The reported anomaly (**50,000 probabilistic rows vs 2 climax events**) was **primarily a replay-environment artifact**:

| Dataset | Rows | Role |
|---------|------|------|
| `probabilistic_auction_memory.parquet` | ~50,000 | Runtime loop exports (every pipeline pass) |
| `candle_structure_memory.parquet` | ~350 | **Ontology denominator** (M15 bars, ~3.6 days) |

**Do not compare climax counts to probabilistic row counts.**

After replay-environment audit and filter waterfall analysis, density collapse was attributed to:

1. **Rolling window NaN edge handling** in `auction_climax_engine_v1.py` (`rolling(50)` without `min_periods=1` on a 350-bar window)
2. **Over-tightened Phase 3A secondary STOPPING filters** (wick 0.25, strict close_position 0.35, strict delta_shift) vs pre-3A runtime
3. **Grey zone** — intentional; not primary collapse driver on current sample
4. **Deduplication** — minimal impact on current sample

---

## 2. Replay Environment Profile

Run:

```bash
venv/bin/python3 scripts/run_ontology_density_diagnostics.py
```

Exports to `reports/ontology_density/`:

- `replay_environment_profile.json`
- `timeframe_density_expectation.json`
- `ontology_density_audit.json`
- `ontology_filter_waterfall.json`
- `grey_zone_review.json`
- `deduplication_review.json`
- `threshold_sanity_review.json`

**Current replay window (local):**

- Timeframe: **M15** (15-minute bars)
- Duration: ~**3.6 days** (~350 candles)
- Probabilistic span: ~12 days of runtime ticks (different cadence)

**Conclusion:** Sparse absolute event counts on 350 bars are expected; invalid cross-dataset comparison inflated severity.

---

## 3. Filter Waterfall Findings

On the current M15 sample (350 bars):

| Stage | Finding |
|-------|---------|
| Sell-side base candidates | ~5 rows |
| Grey zone absorption | ~2 rows (by design) |
| Post semantic separation (pre-fix) | **0** sell-side labels |
| Legacy (pre-3A) | 3 `STOPPING_VOLUME`, 1 `SELLING_CLIMAX` |

**Collapse stage:** `post_wick_filter_stopping` + `post_delta_filter_stopping` + rolling NaN percentiles excluding early-window candidates.

---

## 4. What Was Restored (No Semantic Redesign)

### A. Rolling feature stability (`auction_climax_engine_v1.py`)

- Added `min_periods=1` to rolling percentiles and range windows
- Fixes NaN `volume_percentile_50` on finite structure memory (Stage 1 window)

### B. Configurable secondary STOPPING discriminators (`ontology_config.py`, `ontology_refinement.py`)

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| `STOPPING_MIN_LOWER_WICK_RATIO` | 0.25 (hardcoded) | **0.15** | Legacy runtime used 0.10; 3A over-tightened |
| `STOPPING_MIN_CLOSE_POSITION_RATIO` | 0.35 (hardcoded) | **0.20** | Recovery proxy without reintroducing lookahead |
| `STOPPING_MIN_DELTA_SHIFT` | 0.0 | **-0.15** | Allow weakening aggression path |
| `STOPPING_RECOVERY_SCORE_ALT` | — | **0.40** | Alternative absorption path (no `future_return_3`) |
| `SELLING_MAX_LOWER_WICK_RATIO` | 0.20 | **0.25** | Slight sell-side secondary alignment |

**Preserved:**

- Effort/result grey zone (0.85–1.20)
- STOPPING before SELLING mutual exclusion
- Phase 3B stabilization
- Probabilistic discipline
- No `future_return_3` in refined runtime path

### C. Post-event evolution dtype fix (`post_event_evolution.py`)

- `climax_resolution_behavior` uses object dtype (fixes legacy replay crash)

---

## 5. Verification

```bash
venv/bin/python3 scripts/verify_ontology_density_restoration.py
venv/bin/python3 scripts/verify_phase3a_ontology.py
venv/bin/python3 scripts/verify_phase3b_stabilization.py
```

---

## 6. Remaining Constraints

- **Short replay window:** 350 M15 bars limits absolute event counts; extend `candle_structure_memory` for production burn-in validation.
- **SELLING_CLIMAX density:** Refined architecture requires `efficiency_decay > 1.20` (capitulation zone). Legacy combined zones; do **not** revert semantic collapse fix.
- **Architecture docx:** Not present in repo — attach `Full Trading System Architecture Stage1 Stage2 Ru V1.docx` for final threshold cross-check.

---

## 7. Out of Scope (Unchanged)

- No new ontology classes
- No probabilistic / calibration / execution changes
- No autonomous reinterpretation
- No artificial signal injection

---

*Generated as part of ontology density restoration workflow.*
