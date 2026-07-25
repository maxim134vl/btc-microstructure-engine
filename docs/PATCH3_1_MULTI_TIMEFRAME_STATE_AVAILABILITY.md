# PATCH 3.1 — Multi-Timeframe State Availability Audit and Canonical Contract

**Tag:** `20260724_164253`  
**Branch:** `memory/canonical-system`  
**Mode:** observational / candidate-only (no production consumer changes)

---

## A. Result

```text
PATCH3_MTF_AVAILABILITY_CONTRACT_READY
```

Five timeframes inventoried; completed-bar + availability enum defined; candidate as-of read-model has `future_joins=0`; production paper/context/decision consumers unchanged.

---

## B. Runtime Preservation

| Process | PID | Status |
| --- | --- | --- |
| Feed watchdog | 10748 | RUNNING |
| Feed | 95055 | RUNNING |
| Pipeline `run.py` | 96691 | RUNNING |
| Context refresher | 97695 | RUNNING |
| Paper controller | 79502 | RUNNING (`--skip-refresh`) |
| Visual refresher | 96805 | RUNNING |

No Patch 3.1 restarts. Paper ledger SHA unchanged. Context/lifecycle/decision may advance via dedicated refresher independently.

Artifact: `data/research/patch3_1_preflight_20260724_164253.json`

---

## C. MTF Lineage

| TF | Source | Transform | Live persist | Writer class |
| --- | --- | --- | --- | --- |
| M15 | `live_market_feed` → `candle_structure_memory` | candle engine | yes (dense) | RUNNING |
| M30 | resample M15 | `aggregate_behavioral_timeframe` + climax | in-memory → Stage-2 synthesis events | EVENT_DRIVEN |
| H1 | resample M15 | same | in-memory → synthesis | EVENT_DRIVEN |
| H4 | resample M15 | same | in-memory → synthesis | EVENT_DRIVEN |
| D1 | resample M15 | dashboard/UI helper | **no Stage-2 writer** | NOT_IMPLEMENTED |

Authoritative event log: `multi_timeframe_synthesis` / `runtime_cognition_memory` (written by `stage2_cognition_runtime_v1.py`, not the cognition engine).

Legacy HTF (`htf_structure*`) + `auction_synthesis`: DISCONNECTED / ACTIVE_BROKEN.

CSV: `data/research/patch3_1_mtf_lineage.csv`

---

## D. Dataset Inventory

| Class | Examples |
| --- | --- |
| ACTIVE_AUTHORITATIVE | live feed, candle_structure |
| EVENT_SPARSE_BY_DESIGN | multi_timeframe_synthesis, runtime_cognition, volume_response |
| ACTIVE_BROKEN | auction_synthesis |
| INACTIVE_DEPRECATED | htf_structure*, htf_ltf_context* |
| STALE_LEGACY | runtime_cognition_composite |
| RESEARCH_ONLY | D1 on-demand, patch3_1 candidate |

JSON: `data/research/patch3_1_mtf_dataset_inventory.json`

---

## E. Timestamp Contract

| Field | Meaning |
| --- | --- |
| M15 `timestamp` | **BAR_OPEN_TIME** (Binance closed kline open) |
| Completed bar close | `open + timeframe_duration` |
| HTF resample label | pandas left label = **BAR_OPEN_TIME** |
| Canonical PIT rule | `source_bar_close <= evaluation_timestamp` |
| Synthesis/VR risk | some writers use processing/wall-clock — not used as HTF bar authority here |

Config: `config/multi_timeframe_availability_contract.json`

---

## F. Completed-Bar Rules

```text
M15 close = open + 15m
M30 close = open + 30m
H1  close = open + 1h
H4  close = open + 4h
D1  close = open + 1D (UTC)
```

Partial / unclosed bars are rejected by as-of helper. M30 is two M15 bars under pandas `30min` UTC boundaries.

---

## G. Sparsity Findings

| Finding | Classification |
| --- | --- |
| Completed M30/H1/H4/D1 bars exist via resample | NORMAL |
| Persisted synthesis rows << completed bars | NORMAL_EVENT_SPARSE |
| D1 absent from Stage-2 write path | RESEARCH_ONLY / NOT_IMPLEMENTED live writer |
| `auction_synthesis` tip frozen | DEFECT (ACTIVE_BROKEN), out of Patch 3.1 activation scope |
| No event row ≠ no state | CONTRACT (availability ≠ market semantics) |

CSV: `data/research/patch3_1_mtf_sparsity_analysis.csv`

---

## H. Availability Contract

Statuses:

```text
FRESH_EVENT
AVAILABLE_LAST_CONFIRMED
WAITING_FOR_BAR_CLOSE
NO_EVENT_STATE_UNCHANGED
UPSTREAM_STALE
WRITER_STALE
WRITER_DEAD
DATASET_MISSING
SCHEMA_INVALID
TIMEFRAME_DEPRECATED
INSUFFICIENT_HISTORY
UNKNOWN
```

Freshness thresholds are **per-timeframe** in the config (D1 not stale after one M15 hour).

Helper: `scripts/research/multi_timeframe_availability.py` → `get_timeframe_state_asof(...)`.

---

## I. Candidate Read-Model

Path: `data/research/patch3_1_candidate_mtf_availability.parquet`  
Meta: `...meta.json`

- Window: last 64 completed M15 evaluation anchors (+ latest runtime)
- Rows: 325 (5 TF × anchors)
- Status mix (rebuild): AVAILABLE_LAST_CONFIRMED / FRESH_EVENT / NO_EVENT_STATE_UNCHANGED
- `production_write_allowed=false`
- State label in candidate uses bar geometry (`bullish`/`bearish`) as non-semantic operational placeholder — **not** forced NEUTRAL/BALANCE/OBSERVE

---

## J. No-Look-Ahead

```text
future_joins = 0
unclosed_bar_joins = 0
duplicate_source_keys = 0
```

CSV: `data/research/patch3_1_no_lookahead_audit.csv`

---

## K. Consumer Audit

Paper does **not** read HTF parquet. Lifecycle/decision use runtime cognition as freshness diagnostic (45m), not as MTF directional veto. Visual/dashboard recompute TF maps on demand. Event-sparse→OBSERVE chain **not proven**.

JSON: `data/research/patch3_1_mtf_consumer_audit.json`

---

## L. Semantic Preservation

- No new NEUTRAL/BALANCE/OBSERVE invented for missing events
- Hierarchy remains observational (no H4/D1 veto)
- No paper/decision/lifecycle logic changes
- Comparison: `EXPECTED_AVAILABILITY_ENRICHMENT`; `UNEXPLAINED=0`

---

## M. Live Cycles

Natural M15 evaluations show:

- M15 updates every close (`FRESH_EVENT` / `NO_EVENT_STATE_UNCHANGED`)
- M30/H1/H4/D1 hold `AVAILABLE_LAST_CONFIRMED` between own closes
- `is_new_event=true` only on own completed boundary

Artifact: `data/research/patch3_1_live_cycles_20260724_164253.json`

---

## N. Tests

```text
tests/test_patch3_1_multi_timeframe_availability.py  → passed
regression (MTF health, context daemon, 2B.2/2B.3, freshness, no-repaint) → 81 passed, 1 skipped
```

---

## O. Safety

| Check | Status |
| --- | --- |
| Production consumers unchanged | yes |
| Paper unchanged / `--skip-refresh` | yes |
| No execution / exchange | yes |
| CONTINUATION=0 / PRICE_GATE=OFF | yes |
| No Patch 3.2 / 4 / 5 | yes |
| No commit/push | yes |

---

## P. Next Step

```text
PATCH 3.2 — MULTI-TIMEFRAME AVAILABILITY RUNTIME ACTIVATION
```

Not started here.

---

## Acceptance gates

```text
all_timeframes_inventoried = true
timestamp_contract_defined = true
completed_bar_contract_defined = true
availability_enum_defined = true
candidate_read_model_created = true
future_joins = 0
unclosed_bar_joins = 0
duplicate_source_keys = 0
synthetic_neutral_states = 0
unexplained_divergences = 0
production_consumer_changes = 0
production_semantic_changes = 0
exchange_calls = 0
```

---

## Artifacts index

| Path | Role |
| --- | --- |
| `config/multi_timeframe_availability_contract.json` | Contract |
| `scripts/research/multi_timeframe_availability.py` | As-of helper |
| `scripts/research/patch3_1_build_mtf_availability_audit.py` | Builder |
| `data/research/patch3_1_preflight_20260724_164253.json` | Preflight |
| `data/research/patch3_1_mtf_lineage.csv` | Lineage |
| `data/research/patch3_1_mtf_dataset_inventory.json` | Inventory |
| `data/research/patch3_1_mtf_sparsity_analysis.csv` | Sparsity |
| `data/research/patch3_1_mtf_consumer_audit.json` | Consumers |
| `data/research/patch3_1_candidate_mtf_availability.parquet` | Candidate |
| `data/research/patch3_1_candidate_mtf_availability.meta.json` | Candidate meta |
| `data/research/patch3_1_no_lookahead_audit.csv` | PIT audit |
| `data/research/patch3_1_candidate_comparison.json` | Comparison/gates |
| `data/research/patch3_1_live_cycles_20260724_164253.json` | Live cycles |
| `data/research/patch3_1_preservation_20260724_164253.json` | Preservation |
| `docs/PATCH3_1_MULTI_TIMEFRAME_STATE_AVAILABILITY.md` | This report |
