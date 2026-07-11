# Model Summary Freshness Guard

Dashboard-only layer that distinguishes **current**, **stale**, and **missing**
model governance / validation diagnostics. It does **not** retrain models,
change the active model, mutate the pipeline, or touch execution / market-context
lifecycle logic.

## Sources the dashboard reads

| Model Summary field | Primary source | Fallback |
|---|---|---|
| Shadow macro F1 | `exports/model_governance_dashboard.json` → `shadow_metrics_last_5000.macro_f1` | latest row of `data/ml/model_monitoring_memory.parquet` (`macro_f1`) |
| Balanced accuracy | governance JSON `shadow_metrics_last_5000.balanced_accuracy` | monitoring parquet `balanced_accuracy` |
| Loss recall | governance JSON / monitoring parquet `loss_recall` | — |
| PSI | monitoring parquet `psi_label` (Drift Monitoring) | — |
| Last validation | governance JSON `last_validation_at` | monitoring parquet `timestamp` |
| Governance status | derived from monitoring + governance JSON | annotated with `+STALE` when stale |
| Active model | governance JSON `active_model` | shown as `MISSING` when empty |
| Candidate model | governance JSON `candidate_model` | shown as `MISSING` when empty |
| Promotion eligible | monitoring / governance rules | forced `NO` when governance is stale |
| Toxic Box baseline / events | `toxic_box_memory.parquet` | — |
| Economic Validation rolling / pending / complete | `economic_validation_memory.parquet` (+ trading validation memory for row counts) | — |

Resolved via `dashboard/backend/app/services/research_pipeline_service.py` and
path aliases in `dashboard_paths.py`.

## Freshness thresholds

Configured in `dashboard/backend/app/config.py` (env-overridable):

| Block | Env var | Default `max_age_hours` |
|---|---|---|
| Governance / model validation | `DASHBOARD_MODEL_GOVERNANCE_MAX_AGE_HOURS` / `DASHBOARD_MODEL_VALIDATION_MAX_AGE_HOURS` | **168** (7 days) |
| Drift monitoring | `DASHBOARD_MODEL_DRIFT_MAX_AGE_HOURS` | **168** |
| Toxic box | `DASHBOARD_MODEL_TOXIC_MAX_AGE_HOURS` | **168** |
| Economic validation (live rolling) | `DASHBOARD_MODEL_ECONOMIC_MAX_AGE_HOURS` | **48** |
| Benchmark reports | `DASHBOARD_MODEL_BENCHMARK_MAX_AGE_HOURS` | **168** |

Timestamp preference:

1. Artifact timestamp inside the file / JSON (`last_validation_at`, monitoring `timestamp`, toxic routed time, economic `completed_at`, …)
2. Else file `mtime`
3. Else `MISSING_DATA` / `UNKNOWN_FRESHNESS`

## Freshness statuses

- `CURRENT` — within threshold
- `STALE_VALIDATION` — validation / economic / shadow older than threshold
- `STALE_GOVERNANCE_DATA` — governance block stale
- `STALE_DRIFT_DATA` — drift / PSI block stale
- `MISSING_DATA` — artifact absent
- `UNKNOWN_FRESHNESS` — path exists but no usable timestamp/mtime

Each block also exposes:

```text
freshness:
  source_path, source_timestamp, source_mtime,
  age_hours, age_days, is_stale, stale_reason, max_age_hours
```

plus `metrics_scope` (`current` | `historical` | `missing` | `unknown`).

## How to interpret stale metrics

- Metrics may still be shown, but only as **historical**.
- Do not treat PASS / MONITOR / REVIEW as live health without the stale warning.
- Model Summary top status becomes **ATTENTION** with reason
  `model validation data stale`.
- Governance shows base status plus `+STALE` (e.g. `DRIFT_WARNING+STALE`).
- `promotion_eligible` is forced to **NO**.
- Empty active/candidate model strings render as **MISSING**, not `—`.
- Toxic “Baseline loaded” becomes **Baseline loaded (STALE)** when stale.

Example warning copy:

> Data is stale. Last validation was 2026-06-14. Metrics are historical.

## How to refresh validation manually

The dashboard **never** starts retrain or validation by itself.

Manual options (operator-run):

1. Preferred when present in the repo: `scripts/retrain_models.py`
   (referenced by the Governance card as the weekly manual retrain note).
2. If that script is not checked in yet, refresh the upstream artifacts that the
   dashboard reads:
   - regenerate / update `data/ml/model_monitoring_memory.parquet`
   - regenerate `exports/model_governance_dashboard.json` (if used)
   - update toxic / economic validation memories via the existing offline
     validation / monitoring jobs used by the research stack
3. Related offline tooling lives under `scripts/replay_validation/` and
   benchmark runners (`scripts/run_*_benchmark.py`) — these are research /
   conformance jobs, not live promotion.

After artifacts are refreshed within the thresholds above, Model Summary returns
to non-stale statuses without any dashboard code change.

## Why the dashboard does not auto-retrain

- Retrain and promotion are **governance decisions**, not UI side effects.
- Auto-retrain from a monitoring panel would mutate model artifacts and risk
  silent promotion eligibility changes.
- Stage 10 only adds a **freshness guard** so June (or older) diagnostics cannot
  be mistaken for July (current) health.
