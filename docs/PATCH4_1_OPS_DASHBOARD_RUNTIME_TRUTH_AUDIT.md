# PATCH 4.1 — OPS Dashboard Runtime Truth Audit and Parity Contract

**Tag:** `20260724_175556`  
**Branch:** `memory/canonical-system`  
**Mode:** audit + research candidate only (no production UI / runtime writer changes)

---

## A. Result

```text
PATCH4_OPS_DASHBOARD_PARITY_CONTRACT_READY
```

Runtime inventory proven (20 engines). Dashboard mismatches fully classified (24 entries = 18 exact + 6 phantoms; 2 runtime-only). Candidate OPS truth payload ready. Production dashboard/frontend unchanged.

---

## B. Runtime Preservation

| Process | PID (preflight) | Status |
| --- | --- | --- |
| Feed watchdog | 10748 | RUNNING |
| Intrabar feed | 93404 | RUNNING |
| Pipeline `run.py` | 20041 | RUNNING |
| Context refresher | 97695 | RUNNING |
| Paper controller | 79502 | RUNNING (`--skip-refresh`) |
| Visual refresher | 96805 | RUNNING |

No process restarts. Artifact: `data/research/patch4_1_preflight_20260724_175556.json`

---

## C. Actual Runtime Inventory

### Processes
FEED, PIPELINE, CONTEXT_REFRESHER, PAPER_CONTROLLER, DASHBOARD_REFRESHER (+ watchdog)

### Pipeline engines (20) — authoritative source
`src/btc_ml/runtime/pipeline.py::CANONICAL_PIPELINE`

Includes:

- `auction_context_arbitration_engine_v1.py`
- `mtf_availability_runtime_engine_v1.py` (Patch 3.2 operational read-model)

### Datasets / read-models
Ownership registry + `runtime_dataset_status.json` + MTF availability latest/status.

Artifact: `data/research/patch4_1_runtime_engine_inventory.json`

---

## D. Dashboard Inventory

Authoritative for **current UI list** only (stale):

`dashboard/backend/app/pipeline_metadata.py` — **24** engines, `EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = 24`

Served by:

- `GET /api/v1/ops/snapshot` ← `ops_monitor.build_ops_snapshot`
- React `OpsDashboard.tsx` / `MonitorPanels.tsx`

Does **not** consume `data/runtime/runtime_dataset_status.json`.

Artifact: `data/research/patch4_1_dashboard_engine_inventory.json`

---

## E. Engine Parity

| Metric | Value |
| --- | ---: |
| runtime_engine_count | 20 |
| dashboard_engine_count | 24 |
| exact_matches | 18 |
| runtime_only | 2 |
| dashboard_only_phantom | 6 |
| duplicates | 0 |
| wrong_mappings | 0 |
| unexplained | 0 |

**Runtime-only**

1. `auction_context_arbitration_engine_v1.py`
2. `mtf_availability_runtime_engine_v1.py`

**Phantoms (file missing)**

1. `volume_localization_engine_v1.py`
2. `market_state_engine_v1.py`
3. `trading_state_engine_v1.py`
4. `shadow_inference_engine_v1.py`
5. `trading_state_validation_engine_v1.py`
6. `economic_validation_engine_v1.py`

Artifact: `data/research/patch4_1_engine_parity.csv`

---

## F. Data Lineage

```text
runtime process / dataset
→ ownership registry / metadata / specialized status / ps inspection
→ candidate ops payload (research)
→ (future Patch 4.2) dashboard generator
→ frontend mapping
→ rendered card
```

Current production lineage still starts from **hardcoded dashboard pipeline_metadata**, which is the primary defect.

Artifact: `data/research/patch4_1_dashboard_lineage.csv`

---

## G. Entity Taxonomy

```text
PROCESS
PIPELINE_ENGINE
DATASET
READ_MODEL
UNSUPPORTED_CAPABILITY
LEGACY_COMPONENT
```

Rules:

- dataset ≠ process
- engine ≠ daemon
- missing PID ≠ broken dataset
- event-sparse ≠ failed engine
- D1 unsupported ≠ system BROKEN

---

## H. Canonical Sources (priority)

1. live process inspection  
2. runtime dataset ownership registry  
3. metadata sidecars  
4. `runtime_dataset_status.json`  
5. pipeline cycle status  
6. specialized statuses (MTF / paper / context refresher / watchdog)

Forbidden as primary: hardcoded JS arrays, stale research JSON, previous dashboard payload, mtime-only, README.

---

## I. Health Semantics

Overall levels:

```text
HEALTHY
HEALTHY_WITH_KNOWN_LIMITATIONS
DEGRADED
BROKEN
UNKNOWN
```

Current candidate overall:

```text
HEALTHY_WITH_KNOWN_LIMITATIONS
```

Reason: core processes up; D1 not live; `auction_synthesis` broken/non-required; paper no-trade is informational.

---

## J. MTF Representation

Source: `data/runtime/multi_timeframe_availability_latest.json`

| TF | Support | Contract |
| --- | --- | --- |
| M15–H4 | LIVE_SUPPORTED | availability_status / state_asof / source_bar_close / is_new_event |
| D1 | RESEARCH_ONLY_NOT_LIVE | `TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER` |

`AVAILABLE_LAST_CONFIRMED` is not treated as error.

---

## K. Paper Representation

```text
RUNNING / NO_ELIGIBLE_TRADE
```

`OBSERVE_NO_TRADE` ≠ controller failure. Distinct from STOPPED / UPSTREAM_STALE / BROKEN.

---

## L. Context Representation

Allowed results:

```text
REFRESH_SUCCESS
NO_NEW_SAFE_UPSTREAM
PIPELINE_PENDING
REFRESH_FAILED
```

`NO_NEW_SAFE_UPSTREAM` is a normal no-op.

---

## M. Broken and Deprecated

| Component | Representation |
| --- | --- |
| `auction_synthesis` | ACTIVE_BROKEN / non-required known limitation |
| OI / legacy HTF | INACTIVE_DEPRECATED / LEGACY_COMPONENT |
| 6 phantom engines | PHANTOM → legacy section, not active engine list |

---

## N. Candidate Payload

```text
data/research/patch4_1_candidate_ops_dashboard.json
data/research/patch4_1_candidate_ops_dashboard.meta.json
```

Schema sections: `processes[]`, `pipeline_engines[]`, `datasets[]`, `multi_timeframe[]`, `paper{}`, `context_chain{}`, `known_limitations[]`, `legacy_components[]`, `alerts[]`.

`production_write_allowed = false`.

---

## O. Frontend Findings

Primary defects:

- hardcoded 24-engine list in `pipeline_metadata.py`
- `ops_monitor` iterates that list
- does not read `runtime_dataset_status.json`
- does not use Patch 3.2 MTF availability contract as primary
- offline fallback may imply healthy/static world
- research UI still references phantom-era modules

Artifact: `data/research/patch4_1_frontend_audit.json`

---

## P. Tests

`tests/test_patch4_1_ops_dashboard_truth_audit.py` — inventory/parity/taxonomy/MTF/paper/context/health/readonly/preservation gates.

Also retain Patch 2/3 regressions as applicable.

---

## Q. Safety

- production dashboard payload/UI unchanged
- runtime writers unchanged
- no trading semantics
- no exchange
- no Patch 4.2 / Patch 5
- no commit/push

---

## R. Next Step

After:

```text
PATCH4_OPS_DASHBOARD_PARITY_CONTRACT_READY
```

next stage (**not started**):

```text
PATCH 4.2 — OPS DASHBOARD RUNTIME TRUTH PRODUCTION ACTIVATION
```
