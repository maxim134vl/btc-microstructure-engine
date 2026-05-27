# RUNTIME LINEAGE MAP

**Status:** Canonical reference (Phase 0B integrity hardening)  
**Updated:** 2026-05-27  
**Scope:** Observability only — no behavioral recalibration

---

## 1. Purpose

Phase 0B adds explicit lineage metadata to cognition propagation parquets so runtime state can be audited end-to-end:

- Which engine produced a row
- Which upstream parquet supplied the event
- Market/event timestamp origin
- Propagation (write) timestamp
- Dependency chain from source → engine → output

Shared helper: **`runtime_lineage.py`**

---

## 2. Lineage Columns (All Target Parquets)

| Column | Type | Meaning |
|--------|------|---------|
| `lineage_engine` | string | Engine module that wrote the row |
| `lineage_source_parquet` | string | Immediate upstream parquet input |
| `lineage_event_timestamp` | datetime | Market/cognition event time (`timestamp` column) |
| `lineage_propagation_timestamp` | datetime | UTC time when row was written |
| `lineage_dependency_chain` | string | `->`-joined propagation path |

---

## 3. Target Parquets

| Parquet | Writer | Source | Dependency chain |
|---------|--------|--------|------------------|
| `multi_timeframe_synthesis.parquet` | `stage2_cognition_runtime_v1.py` | `candle_structure_memory.parquet` | `candle_structure_memory.parquet` → `stage2_cognition_runtime_v1.py` → `multi_timeframe_synthesis.parquet` |
| `runtime_cognition_memory.parquet` | `stage2_cognition_runtime_v1.py` | `multi_timeframe_synthesis.parquet` | `candle_structure_memory.parquet` → `stage2_cognition_runtime_v1.py` → `multi_timeframe_synthesis.parquet` → `runtime_cognition_memory.parquet` |
| `auction_reinforcement_memory.parquet` | `auction_reinforcement_engine_v1.py` | `auction_synthesis_memory.parquet` + `STATE["runtime_cognition"]` | `runtime_cognition_memory.parquet` → `auction_synthesis_memory.parquet` → `volume_response_state.parquet` → `auction_reinforcement_engine_v1.py` → `auction_reinforcement_memory.parquet` |
| `probabilistic_auction_memory.parquet` | `probabilistic_auction_engine_v1.py` | `auction_reinforcement_memory.parquet` + `STATE["runtime_cognition"]` | `runtime_cognition_memory.parquet` → `auction_reinforcement_memory.parquet` → `probabilistic_auction_engine_v1.py` → `probabilistic_auction_memory.parquet` |

---

## 4. Alignment Integrity (V-003)

**Module:** `runtime_integrity.py`  
**Consumer:** `runtime_cognition_engine_v1.py`

| Status | Meaning | STATE behavior |
|--------|---------|----------------|
| `VALID` | Numeric score in `[0, 1]` consistent with synthesis | `alignment_score` populated |
| `MISSING` | No score after merge attempt | `alignment_score = None`, error logged |
| `INVALID` | Non-numeric or out of range | `alignment_score = None`, error logged |
| `STALE` | Score diverges from synthesis or latest cognition lags synthesis | warning logged, no default injection |

Invalid/missing/stale rows are exported to:

- `runtime_cognition_alignment_audit.parquet`

**Removed:** silent `fillna(0.25)` fallback in `runtime_cognition_engine_v1.py`

Downstream engines (`auction_reinforcement_engine_v1.py`, `probabilistic_auction_engine_v1.py`) read `alignment_status` from STATE and skip alignment contribution when not `VALID`.

---

## 5. Conviction Decomposition Export

Export-only fields (no recalibration) on reinforcement and probabilistic rows:

| Field | Source engine | Meaning |
|-------|---------------|---------|
| `reinforcement_component` | both | Base structural/reinforcement contribution before cognition multipliers |
| `alignment_component` | both | Alignment delta (reinforcement) or multiplier (probabilistic) |
| `persistence_component` | both | Persistence score / additive persistence contribution |
| `location_component` | both | Location bias contribution |
| `unfinished_auction_component` | both | Unfinished auction flag contribution |
| `entropy_penalty` | both | Shannon entropy of belief window (observability metric) |
| `conflict_penalty` | both | Conflict score from reinforcement path |

Probabilistic also exports `conviction_probability` (final) unchanged in formula except alignment multiplier skipped when alignment invalid.

---

## 6. Timestamp Drift Validation

**Module:** `runtime_integrity.compute_drift_metrics()`

Checks (warning-only, no hard stop):

- Cognition timestamp monotonicity
- Cognition vs synthesis event lag
- Parquet propagation lag (mtime)
- Reinforcement staleness vs cognition
- Candle structure staleness vs cognition

Metrics attached to `STATE["runtime_cognition"]["drift_metrics"]` each cognition load cycle.

---

## 7. Verification

```bash
cd /Users/fontecrypto/btc-ml
venv/bin/python3 scripts/verify_phase0b_integrity.py
```

Checks:

1. Lineage columns on all four target parquets
2. Alignment integrity (no fake default injection)
3. Timestamp drift metrics in STATE
4. Conviction decomposition columns exported
5. No stale cognition injected into STATE

---

## 8. Related Modules

| Module | Role |
|--------|------|
| `runtime_lineage.py` | Lineage column builder |
| `runtime_integrity.py` | Alignment classification, drift metrics, audit export |
| `runtime_cognition_engine_v1.py` | Cognition load + integrity gates |
| `stage2_cognition_runtime_v1.py` | Stage 2 export with lineage |
| `auction_reinforcement_engine_v1.py` | Reinforcement export + decomposition |
| `probabilistic_auction_engine_v1.py` | Probabilistic export + decomposition |

---

*See also: `docs/PARQUET_DEPENDENCY_MAP.md`, `docs/CANONICAL_RUNTIME_MAP.md`*
