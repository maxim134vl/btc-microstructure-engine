# PATCH 4.2 — OPS Dashboard Runtime Truth Production Activation

**Status:** `PATCH4_OPS_DASHBOARD_RUNTIME_TRUTH_ACTIVATED`  
**Tag:** `20260724_182146`  
**Branch:** `memory/canonical-system`

## A. Result

Production OPS snapshot (`GET /api/v1/ops/snapshot`) now builds from the shared canonical runtime truth module. Active pipeline engines = **20**. Phantom active entries = **0**. Overall health = **HEALTHY_WITH_KNOWN_LIMITATIONS**. Model runtime processes were not restarted.

## B. Production Files

| Path | Role |
| --- | --- |
| `ops_dashboard_runtime_truth.py` | Shared read-only truth builder |
| `dashboard/backend/app/pipeline_metadata.py` | AST-synced canonical 20-engine inventory |
| `dashboard/backend/app/services/ops_monitor.py` | Wires truth plane into `/ops/snapshot` |
| `dashboard/backend/app/services/research_pipeline_service.py` | Ribbon label `PIPELINE` (was `PIPELINE24`) |
| `dashboard/frontend/src/types/ops.ts` | Truth-plane types |
| `dashboard/frontend/src/api/opsFallbackSnapshot.ts` | Offline fallback = 20 engines, no phantoms |
| `dashboard/frontend/src/components/ops/OpsDashboard.tsx` | Data bindings + RuntimeTruthSection (existing components) |
| `dashboard/frontend/src/components/status/researchMappers.ts` | Comment-only sync note |
| `scripts/ops/patch4_2_activate_ops_dashboard_truth.py` | Activation / evidence runner |
| `tests/test_patch4_2_ops_dashboard_runtime_truth.py` | Acceptance tests |

**CSS:** `dashboard/frontend/src/index.css` unchanged.

## C. Backend Truth Builder

Shared module: `ops_dashboard_runtime_truth.py`  
Imported by FastAPI OPS backend, research activation, and tests (single implementation).

Source hierarchy:

1. live process inspection (`ps` identity)
2. `src/btc_ml/runtime/pipeline.py`
3. `config/runtime_dataset_ownership.json`
4. dataset metadata / `data/runtime/runtime_dataset_status.json`
5. specialized runtime status files (MTF / paper / context)
6. latest canonical runtime payloads

Schema version: `ops_snapshot_v2_runtime_truth` (API) / `ops_dashboard_runtime_truth_v1` (truth plane).

## D. Engine Parity

- Active engines: **20**
- Runtime-only now active: `auction_context_arbitration_engine_v1.py`, `mtf_availability_runtime_engine_v1.py`
- Phantoms removed from active list (retained as `legacy_components[]` / `PHANTOM`):
  - volume_localization, market_state, trading_state, shadow_inference, trading_state_validation, economic_validation
- Duplicate engine IDs: **0**
- Unexplained divergences: **0**

## E. Processes

Inspected identities (preflight/activation preserved model PIDs):

| process_id | role |
| --- | --- |
| live_feed | required trading plane |
| canonical_pipeline | required trading plane |
| context_refresher | required support |
| paper_controller | required paper plane (`--skip-refresh`) |
| ops_backend | OPS only (not trading pipeline) |
| dashboard_refresher | visual refresher (non-required) |

OPS backend restart only is allowed / performed.

## F. Datasets

Ownership registry + `runtime_dataset_status.json`. Health not derived from mtime alone. Fail-closed `UNKNOWN` when status row missing.

## G. MTF

From `multi_timeframe_availability_latest.json` / `_status.json`:

- M15 / M30 / H1 / H4: live-supported statuses
- D1: `TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER`, `state_asof=null`, not promoted from research

## H. Context Chain

Block exposes process health, last result, tips, lag.  
`NO_NEW_SAFE_UPSTREAM` / `REFRESH_SUCCESS` / `PIPELINE_PENDING` = healthy operational states.  
`REFRESH_FAILED` = degraded/error path.

## I. Paper

Block exposes process health, mode, skip_refresh, real_execution=false, cycle result.  
`OBSERVE_NO_TRADE` / `RUNNING_NO_ELIGIBLE_TRADE` = healthy operational (not controller failure).

## J. Known Limitations

- `D1_NOT_LIVE` — unsupported capability
- `AUCTION_SYNTHESIS_ACTIVE_BROKEN` — `WRITER_DISCONNECTED`, `required_by_current_runtime=false`
- Deprecated OI / disconnected HTF — `INACTIVE_DEPRECATED`, non-required

## K. API

`GET /api/v1/ops/snapshot` returns legacy-compatible fields plus:

`overall_health`, `overall_reason`, `processes`, `pipeline_engines`, `datasets`, `multi_timeframe`, `context_chain`, `paper`, `known_limitations`, `legacy_components`, `runtime_truth`, `alerts`.

## L. Frontend

- No hardcoded 24-engine list / phantoms
- Fallback + live cards use 20 canonical engines
- RuntimeTruthSection reuses `PanelCard` / `ListRow` / `SectionLabel`
- Null/UNKNOWN fail-closed (not green)

## M. Live Cycles

Activation sampled natural cycles; process PIDs for feed/pipeline/context/paper preserved. Frontend consumes refreshed snapshot fields.

## N. Tests

`tests/test_patch4_2_ops_dashboard_runtime_truth.py` covers inventory parity, phantoms, MTF/D1, paper/context semantics, overall health rules, read-only, flags, API schema, frontend contracts.

## O. Preservation

Artifact: `data/research/patch4_2_preservation_20260724_182146.json`  
Model process restarts = 0; historical runtime sha unchanged for MTF/context/decision/paper signals.

## P. Safety

- Dashboard read-only (no writers / refresh / paper actions)
- No exchange / real execution
- CONTINUATION OFF / PRICE_GATE OFF surfaces preserved
- No Patch 5 / trade-chart / D1 live writer
- No commit/push

## Visual Preservation

Frontend files touched only for data bindings / entity lists / status mapping.  
CSS theme, fonts, grid, card chrome unchanged (`css_unchanged=true`).  
No redesign / modernization / component library swap.

Expected outcome:

> Текущий production-дизайн OPS dashboard сохранён.  
> Изменены только runtime data bindings, entity lists и status mappings.  
> Редизайн не проводился.

## Artifacts

- `data/research/patch4_2_preflight_20260724_182146.json`
- `data/research/patch4_2_backup_manifest_20260724_182146.json`
- `data/research/patch4_2_api_comparison_20260724_182146.json`
- `data/research/patch4_2_snapshot_parity_20260724_182146.json`
- `data/research/patch4_2_processes_20260724_182146.json`
- `data/research/patch4_2_live_cycles_20260724_182146.json`
- `data/research/patch4_2_frontend_validation_20260724_182146.json`
- `data/research/patch4_2_preservation_20260724_182146.json`
- `data/research/patch4_2_visual_baseline_20260724_182146.json`
- `data/research/patch4_2_visual_regression_20260724_182146.json`
- `data/research/patch4_2_summary_20260724_182146.json`

## Q. Next Step

Determined separately. Do not auto-start Patch 5.
