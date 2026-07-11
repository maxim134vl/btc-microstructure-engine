# Model Summary Freshness Guard

Dashboard-only layer that distinguishes **current**, **stale**, and **missing**
diagnostics. Stage 11: **benchmark/conformance reports are primary**; legacy
`data/ml/model_monitoring_memory.parquet` is fallback only.

It does **not** retrain models, change the active model, mutate the pipeline,
or touch execution / market-context lifecycle logic. It does **not** generate
benchmark files.

## Sources the dashboard reads

See also [MODEL_SUMMARY_SOURCES.md](./MODEL_SUMMARY_SOURCES.md).

| Field | Primary | Fallback / notes |
|---|---|---|
| Latest diagnostics | `benchmark/conformance/reports/latest_conformance.json` `generated_at` | then `latest_integrated.json` |
| Shadow macro F1 / balanced accuracy / loss recall / PSI | nested keys in conformance / integrated / stage2 / latest summaries | **not** June parquet as current; legacy values under `legacy_*` only |
| Governance status / active / candidate / promotion | `exports/model_governance_dashboard.json` | if missing → `GOVERNANCE_MISSING`, promotion `NO` |
| Legacy model monitoring | `data/ml/model_monitoring_memory.parquet` | shown STALE / `used_as_primary=false` when benchmark fresh |
| Toxic Box | `toxic_box_memory.parquet` (resolved path) | missing → `MISSING_DATA` (no “Baseline loaded” without source/freshness) |
| Economic Validation | `data/diagnostics/economic_validation_memory.parquet` | `source_path` exposed; 48h threshold |

## Freshness thresholds

Configured in `dashboard/backend/app/config.py` (env-overridable):

| Block | Default `max_age_hours` |
|---|---|
| Benchmark / conformance diagnostics | **168** |
| Governance artifact | **168** |
| Drift monitoring (follows diagnostics) | **168** |
| Toxic box | **168** |
| Economic validation (live rolling) | **48** |
| Legacy monitoring (when used alone) | **168** |

## Freshness / attention statuses

- `CURRENT` — diagnostics within threshold
- `STALE_VALIDATION` / `STALE_DRIFT_DATA` / `STALE_GOVERNANCE_DATA`
- `MISSING_DATA` / `GOVERNANCE_MISSING` / `UNKNOWN_FRESHNESS`

Top Model Summary:

- fresh benchmark + missing governance → **ATTENTION** ·
  `governance artifact missing; benchmark diagnostics current`
- stale benchmark → **ATTENTION** · `benchmark diagnostics stale`

## How to interpret metrics

- Metrics from fresh reports → `metrics_scope=current` (or MISSING if key absent)
- June parquet metrics → `legacy_value` / `legacy_is_stale=true` / not primary
- Empty active/candidate → **MISSING**
- Promotion eligible → **NO** when governance missing or stale

## How to refresh manually

The dashboard **never** starts retrain or validation by itself.

1. Refresh diagnostics: run existing benchmark/conformance jobs (operators), which
   update `benchmark/**/latest_*.json` — dashboard only reads them.
2. Refresh governance: produce `exports/model_governance_dashboard.json` via the
   existing governance export / `scripts/retrain_models.py` when available.
3. Legacy parquet remains optional historical context.

## Runtime note (Stage 11.1)

`make runtime-stack` refreshes dashboard API + Vite UI on every start so this
code path is loaded. Endpoint: `GET /api/v1/ops/snapshot` →
`research_pipeline.model_summary` with `model_summary_source_version:
benchmark_primary_v1`.

## Why the dashboard does not auto-retrain

Retrain and promotion are governance decisions. Auto-retrain from a monitoring
panel would mutate model artifacts. Freshness + source priority only prevent
stale or missing artifacts from looking like live health.
