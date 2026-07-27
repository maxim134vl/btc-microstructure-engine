# OPS1C — Live Operations Truth Activation

**Status:** `OPS1_LIVE_OPERATIONS_TRUTH_ACTIVATED`  
**UTC:** 2026-07-27  
**Branch:** `memory/canonical-system`  
**Activated commit:** `95f6204` (`fix: restore OPS truth from active pipeline metadata`)  
**Quarantine:** `data/quarantine/architecture_recovery/ops1c/20260727_085706/`

---

## A. Result

One controlled OPS API-only restart activated OPS1B runtime truth. Live Operations Summary now shows process/trader/context truth, 26 pipeline engines in the API payload, and PID-based runtime uptime. Core pipeline/manager/traders/visualizer were not restarted.

## B. Source Scope

```text
production source changes during activation = 0
```

Docs-only follow-up commit records this activation.

## C. Tests

Pre-restart: `tests/test_ops1b_live_operations_truth_candidate.py` + `tests/test_patch4_2_ops_dashboard_runtime_truth.py` → **54 passed**.

## D. Pre-Activation OPS State

| Field | Before (PID 22716) |
| ----- | ------------------ |
| `runtime_truth_unavailable` | true (`CANONICAL_PIPELINE not found`) |
| processes | 0 / empty |
| traders | empty |
| pipeline engines (truth) | 0 |
| uptime (UI Resources) | host-scale (~1433h) |

Baseline artifacts: `ops_summary_before.json`, `runtime_truth_before.json`, `process_truth_before.json`, `symptoms_before.json`.

## E. OPS API Launch Contract

| Field | Value |
| ----- | ----- |
| old PID | 22716 |
| PPID / PGID | 1 / 22716 |
| started | Sun Jul 26 15:17:20 2026 |
| cwd | `/Users/fontecrypto/btc-ml` |
| argv | `…/Python dashboard/backend/run_api.py` |
| listen | `0.0.0.0:8080` |
| stale pid file | `run/ops_api.pid` → 59248 (cleared after stop) |
| approved relaunch | same argv/cwd; interpreter via `venv/bin/python3` (resolves to same Frameworks Python path; provides `uvicorn`) |
| env parity with pipeline | `BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE=1`, `BTC_ML_VOLUME_LOCALIZATION_LIVE=1` |
| log | `logs/ops_api_ops1c_activation.log` |

First start attempt used Frameworks Python without site-packages → `ModuleNotFoundError: uvicorn` (exited). Immediate completion of the same restart with `venv/bin/python3` + `start_new_session=True`. No duplicate concurrent OPS API processes.

## F. Old / New OPS API PID

| | PID |
| - | --- |
| old | 22716 |
| new | **28285** |
| count | 1 |

## G. API Readiness

| Check | Result |
| ----- | ------ |
| process alive | true |
| listen :8080 | true |
| `/health` | 200 |
| `/api/v1/ops/snapshot` | 200 |
| parser / import loops | none |

## H. Runtime Truth

```text
runtime_truth_unavailable = false
section_errors.pipeline_metadata = absent / empty
overall_health = OPERATIONAL_WITH_LIMITATIONS
```

## I. Pipeline Metadata

| Field | Live |
| ----- | ---- |
| active builder | `canonical_pipeline_with_stage2_synthesis_inputs_candidate` |
| total engines | **26** |
| required health engines | **3** |
| required healthy | **3** |

UI still labels Pipeline card as `3/3 engines` → recorded `OPS_FRONTEND_TOTAL_REQUIRED_LABEL_MISMATCH` (no frontend edits in OPS1C).

## J. Process Truth

| Role | PID | Present |
| ---- | --: | ------- |
| canonical_pipeline | 4618 | yes |
| timeframe_manager | 61283 | yes |
| trader_M15..H4 | 61284–61287 | yes |
| ops_backend | 28285 | yes |
| dashboard_refresher | 84045 | yes |

## K. Manager Truth

| Field | Class |
| ----- | ----- |
| manager process | RESTORED |
| command bus HEALTHY | RESTORED |
| command tip | RESTORED (`2026-07-27T09:00:00Z`) |
| command count / duplicates | RESTORED (959 / 0) |
| risk / PnL | RESTORED from existing manager/portfolio contract (not recalculated) |

## L. Timeframe Traders

M15/M30/H1/H4 all present and running (LONG). No “No traders”.

## M. Context Chain

| Field | Live |
| ----- | ---- |
| last result | REFRESH_SUCCESS |
| context tip | filled (advanced with bar) |
| lifecycle tip | filled |
| decision tip | null / UI `—` — tip helper requires `timestamp` column; log uses `candle_timestamp` (OUTSIDE_CURRENT_CONTRACT; not fixed in OPS1C) |
| trading state / market / bias / intent | LONG_CONTEXT / LONG / INTENT_OPEN_LONG via research decision layer |

## N. Runtime Uptime

API `runtime_truth.runtime_uptime`:

```text
source = pipeline_pid_create_time
host_boot_time_substituted = false
runtime_uptime_seconds ≈ pid age (~3.1h)
```

UI Resources card still shows host-scale `1433h` (separate frontend field) → deferred display follow-up; API contract is PID-based.

## O. Volume Localization Classification

`volume_localization` present in active 26-step list; phantom = false.

## P. Health Semantics

`OPERATIONAL_WITH_LIMITATIONS` (D1 not live; auction_synthesis known non-required).  
Not forced Healthy. Runtime truth unavailable no longer degrades health.

## Q. Alert Semantics

Actionable alerts = 0 after recovery (optional collectors INFO only).  
`OPS-HEALTH-ALERT-CONTRACT-MISMATCH` kept deferred for future degraded-with-zero-alert cases.

## R. Frontend Verification

After hard refresh / reconnect:

- System Health = Operational with Limitations
- Runtime truth error banner absent
- Pipeline Running; tip filled
- Required processes show pipeline/manager/traders
- Timeframe traders M15–H4 present
- Context + lifecycle tips filled
- Decision tip `—` (column contract gap)
- Engine label still `3/3` (frontend mismatch)

Vite PID `66359` not restarted.

## S. Three Polling Cycles

Same OPS API PID **28285**; `generated_at` advanced; steps=26; traders=4; no parser exception. See `three_polls.json`.

## T. Natural M15-Bar Gate

Baseline candle tip `2026-07-27T08:45:00Z` → advanced to `2026-07-27T09:00:00Z` while:

- pipeline PID remained 4618
- OPS API PID remained 28285
- manager/traders present
- context/lifecycle tips available / advanced

Evidence: `m15_gate_baseline.json`, `m15_gate_result.json`.

## U. Canonical Parity

| Field | Canonical | OPS | Parity |
| ----- | --------: | --: | -----: |
| pipeline PID | 4618 | 4618 | 100% |
| total steps | 26 | 26 | 100% |
| manager PID | 61283 | 61283 | 100% |
| M15–H4 PIDs | 61284–61287 | same | 100% |
| context/lifecycle tips | live tips | present | 100% available-field |
| runtime uptime (API) | PID age | PID age | 100% |

## V. Core Process Preservation

```text
pipeline 4618 unchanged
manager 61283 unchanged
traders 61284–61287 unchanged
visual refresher 84045 unchanged
Vite 66359 unchanged
```

## W. Git / Gitea

Docs-only commit: `docs: record live operations truth activation`  
Gitea/GitHub push: **NOT PERFORMED**

## X. Compliance

```text
production source changes during activation = 0
pipeline restarts = 0
manager restarts = 0
trader restarts = 0
visual refresher restarts = 0
frontend restarts = 0
OPS API intentional restarts = 1
OPS API duplicate starts = 0
live trading writes caused by OPS = 0
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

## Y. Next Step

Observe OPS, dashboard, and paper trading stability. Do not start new architectural fixes.
