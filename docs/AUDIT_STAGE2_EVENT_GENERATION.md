# AUDIT: Stage 2 Event Generation

**Date:** 2026-05-29  
**Scope:** Why `multi_timeframe_synthesis.parquet` and `runtime_cognition_memory.parquet` contain 3 rows while `candle_structure_memory.parquet` contains 350 rows.

---

## Executive Summary

**Stage 2 does not use `should_persist_state()`, append logic, or runtime dedup.** It **fully replaces** both parquets on each run via `atomic_parquet_write()`.

The 3-row count is **not** caused by persistence refusal. It is caused by **upstream event gating** in `auction_climax_engine_v1.py`:

1. All **350** M15 candles are evaluated each Stage 2 run.
2. Only rows where `auction_event_type != "NORMAL"` enter `auction_states`.
3. Currently that is **3 rows** (0.86% of candles).
4. `synthesize_multi_timeframe_behavior()` emits **one synthesis row per M15 non-NORMAL row** → **3 synthesis rows**.
5. `export_runtime_cognition_memory()` drops rows with null `synthesis_state` → still **3 rows**.

**Answer to the core question:** Stage 2 **stops generating cognition at the climax/synthesis boundary** for NORMAL candles. It does **not** generate 350 cognition rows and then discard 347 at persist time.

---

## 1. Stage 2 Persistence Logic (`stage2_cognition_runtime_v1.py`)

### 1.1 Full `run()` flow

```
refresh_state()
  → base_dataset = STATE["candle_structure"]     # 350 rows
  → synthesis_output = build_stage2_synthesis()   # climax + MTF synthesis
  → apply_lineage_metadata()
  → atomic_parquet_write(synthesis_output)        # REPLACES multi_timeframe_synthesis.parquet
  → runtime_cognition_memory = export_runtime_cognition_memory()
  → apply_lineage_metadata()
  → atomic_parquet_write(runtime_cognition_memory) # REPLACES runtime_cognition_memory.parquet
```

### 1.2 `should_persist_state()` — **NOT USED**

Stage 2 does **not** import or call `state_guard.should_persist_state()`.

That function exists for other engines (e.g. `volume_response_engine_v1.py`, `auction_synthesis_engine_v1.py`, `probabilistic_auction_engine_v1.py`) and returns `True` only when the new state dict differs from the **last row** of the existing parquet.

Stage 2 bypasses this entirely.

### 1.3 Dedup logic — **NOT IN STAGE 2**

Stage 2 has **no** `dedup_columns`, `drop_duplicates`, or `append_state_row()`.

Dedup that affects event counts lives **upstream** in:

| Location | Mechanism |
|----------|-----------|
| `ontology_refinement.deduplicate_swing_clusters()` | Sell-side swing clusters: keeps strongest event, sets others to `NORMAL` |
| `auction_climax_engine_v1.py` return filter | `auction_states = dataset[dataset["auction_event_type"] != "NORMAL"]` |

### 1.4 Persist mechanism — **FULL REPLACE**

```python
atomic_parquet_write(synthesis_output, SYNTHESIS_OUTPUT_PATH)
atomic_parquet_write(runtime_cognition_memory, RUNTIME_COGNITION_MEMORY_PATH)
```

`atomic_parquet_write()` writes the entire DataFrame and replaces the file. **No merge with history.**

### 1.5 `export_runtime_cognition_memory()` filter

```python
runtime_cognition_memory = synthesis_output[COGNITION_COLUMNS].copy()
runtime_cognition_memory = runtime_cognition_memory.dropna(subset=["synthesis_state"])
```

Only rows missing `synthesis_state` are dropped. With current synthesis output, **0 rows** are dropped by this filter.

---

## 2. Synthesis Generation Logic

### 2.1 `build_stage2_synthesis()`

Runs `process_auction_climax()` on M15, M30, H1, H4 aggregated datasets, then calls `synthesize_multi_timeframe_behavior()`.

### 2.2 Critical: synthesis iterates **M15 non-NORMAL only**

```python
# multi_timeframe_synthesis_engine.py
for _, m15_row in m15_states.iterrows():
    ...
    synthesis_rows.append({...})
```

`m15_states` = `m15_result["auction_states"]` = **only non-NORMAL M15 climax rows**.

Therefore: **synthesis row count == M15 non-NORMAL event count**, not candle count.

### 2.3 State assignment logic (per M15 event)

| Condition | `synthesis_state` | `persistence` | `persistence_score` |
|-----------|-------------------|-----------------|---------------------|
| No M30 window AND no H1 window in ±window | `LOCAL_EXHAUSTION` | `M15_ONLY` | 0.25 |
| M30 window present, H1 window empty | `INTERMEDIATE_REVERSAL` | `M30_CONFIRMED` | 0.50 |
| Else (H1 window present) | `STRUCTURAL_REVERSAL` | `H1_CONFIRMED` | 0.75 |

`alignment_score` increments +0.25 for each of M30, H1, H4 windows present (base 0.25).

### 2.4 Current synthesis output (350 M15 candles)

| timestamp | trigger_event | synthesis_state | persistence |
|-----------|---------------|-----------------|-------------|
| 2026-05-18 06:00:00 | STOPPING_VOLUME | LOCAL_EXHAUSTION | M15_ONLY |
| 2026-05-20 05:00:00 | BUYING_CLIMAX | INTERMEDIATE_REVERSAL | M30_CONFIRMED |
| 2026-05-20 08:30:00 | BUYING_CLIMAX | LOCAL_EXHAUSTION | M15_ONLY |

---

## 3. Upstream Event Gating (Root Cause)

### 3.1 `process_auction_climax()` output filter

```python
return {
    "auction_states": dataset[dataset["auction_event_type"] != "NORMAL"],
    ...
}
```

**347 of 350** M15 candles remain `NORMAL` after:

- BUYING_CLIMAX thresholds (volume ≥90th pct, delta>0, spread ≥60th pct, efficiency decay extremes, range_position >0.80)
- STOPPING_VOLUME / SELLING_CLIMAX via `apply_ontology_pipeline()` (semantic separation + swing dedup)
- HIGH_AVERAGE_VOLUME and other classifiers

### 3.2 Observed M15 events (full 350-candle window)

```
2026-05-18 06:00:00  STOPPING_VOLUME
2026-05-20 05:00:00  BUYING_CLIMAX
2026-05-20 08:30:00  BUYING_CLIMAX
```

### 3.3 Higher timeframe events **not used as synthesis drivers**

M30 detected 2 events (including `2026-05-21 04:00:00 BUYING_CLIMAX`), but synthesis **only loops M15 `auction_states`**. The M30 event on 2026-05-21 never produces a synthesis row because there is no corresponding M15 non-NORMAL row at that timestamp.

H1 and H4: **0 non-NORMAL events** in current window.

---

## 4. Stage 1 vs Stage 2 Event Count Mismatch

| Layer | Rows | Event source |
|-------|------|--------------|
| `candle_structure_memory.parquet` | 350 | All M15 candles (structure memory) |
| Stage 1 benchmark events | ~16 | Native emissions from volume_class, volume_response, cognition, transitions |
| Stage 2 synthesis / cognition | 3 | M15 non-NORMAL climax rows only |

Stage 1 benchmark uses **different extraction** (`benchmark/stage1/event_extractor.py`) — volume classification, volume response, runtime cognition, transitions — not the same filter as Stage 2 climax `auction_states`.

This is **architectural**, not a persistence bug.

---

## 5. Counts Since 2026-05-20

### 5.1 Candles vs events

| Metric | Count |
|--------|-------|
| M15 candles since 2026-05-20 | 151 |
| M15 candles since last event (2026-05-20 08:30) | ~149 |
| M15 non-NORMAL events since 2026-05-20 | **2** (both on 2026-05-20) |
| M15 non-NORMAL events after 2026-05-20 08:30 | **0** |
| New synthesis rows after 2026-05-20 08:30 | **0** |

### 5.2 Per Stage 2 run (each pipeline execution)

| Step | Evaluated | Emitted | Discarded at generation |
|------|-----------|---------|-------------------------|
| M15 climax classification | 350 candles | 3 events | 347 → NORMAL |
| MTF synthesis | 3 M15 events | 3 synthesis rows | 0 |
| Cognition export | 3 synthesis rows | 3 cognition rows | 0 |
| Parquet persist | 3 rows | 3 rows written (full replace) | 0 |

### 5.3 Pipeline run count

Latest `lineage_propagation_timestamp` on all 3 cognition rows: **2026-05-29 08:36:13 UTC** (single batch write).

Exact count of Stage 2 executions since 2026-05-20 is **not logged** in parquet. Without runtime logs, only the **last write timestamp** is observable. Each run re-processes the full 350-row window and overwrites with the same 3 rows if no new M15 climax events appear.

---

## 6. Audit Report Tables

### 6.1 Generated events (persisted)

| # | timestamp | trigger | synthesis_state | structural_rank |
|---|-----------|---------|-----------------|-----------------|
| 1 | 2026-05-18 06:00:00 | STOPPING_VOLUME | LOCAL_EXHAUSTION | LOW |
| 2 | 2026-05-20 05:00:00 | BUYING_CLIMAX | INTERMEDIATE_REVERSAL | MEDIUM |
| 3 | 2026-05-20 08:30:00 | BUYING_CLIMAX | LOCAL_EXHAUSTION | LOW |

### 6.2 Discarded events (never reached synthesis)

| Category | Count | Reason |
|----------|-------|--------|
| M15 candles classified NORMAL | 347 | Failed climax/ontology thresholds |
| M30 BUYING_CLIMAX (2026-05-21 04:00) | 1 | Not an M15 driver row — synthesis loop ignores M30-only events |
| H1 / H4 events | 0 | No non-NORMAL detections |

### 6.3 Persistence rejection reasons

| Rejection type | Count | Applies to Stage 2? |
|----------------|-------|---------------------|
| `should_persist_state()` rejected | 0 | **No** — not used |
| `append_state_row` dedup | 0 | **No** — not used |
| `dropna(synthesis_state)` | 0 | Yes, but none null |
| Upstream NORMAL filter | 347 | **Yes** — pre-synthesis |
| Swing cluster dedup (sell-side) | unknown | Upstream ontology only |

---

## 7. Conclusions

1. **Stage 2 is not silently discarding generated cognition at persist time.**
2. **Stage 2 generates cognition only for M15 non-NORMAL climax events** (currently 3).
3. **Full parquet replace** means history is not accumulated — each run writes the complete current synthesis set.
4. **No new events since 2026-05-20 08:30** because no new M15 candles passed climax thresholds in the subsequent ~149 candles.
5. **Stage 1's 350 rows ≠ Stage 2's 3 events** — different layers, different extraction semantics.

---

## 8. Recommendations (informational)

| Issue | Possible direction |
|-------|-------------------|
| Event density too low for validation | Review climax thresholds / ontology density (see `ontology_density/`) |
| M30/H1 events ignored | Consider synthesis drivers beyond M15-only loop |
| No historical accumulation | Consider `append_state_row()` with dedup on `timestamp` + `synthesis_state` |
| Stage 1 / Stage 2 event mismatch | Document as intentional or align extraction boundaries |

---

*Audit executed against live parquets and simulated `build_stage2_synthesis()` on 2026-05-29.*
