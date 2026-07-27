# VIS0C — Canonical Trading Risk OPS Activation

**Status:** `VIS0_CANONICAL_RISK_TRUTH_ACTIVATED`  
**UTC quarantine:** `20260727_103910`  
**Branch:** `memory/canonical-system`  
**Activated commit:** `3b753e4` (`fix: expose canonical manager risk in OPS`)  
**Quarantine:** `data/quarantine/architecture_recovery/vis0c/20260727_103910/`

---

## A. Result

One controlled OPS API-only restart activated the VIS0B risk adapter. Live `/api/v1/ops/snapshot` now matches manager `portfolio_summary.json`:

```text
Gross open risk = $1000 / $1000
available = $0
open positions = 4
M15/M30/H1/H4 reserved risk = $250 each
risk_source = data/trading/manager/portfolio_summary.json
```

Pipeline / manager / traders / visual refresher PIDs unchanged.

---

## B. Preflight

| Check | Result |
| ----- | ------ |
| branch | `memory/canonical-system` |
| HEAD | `3b753e4` |
| pipeline | 4618 |
| OPS API (old) | 28285 |
| manager | 61283 |
| traders | 61284–61287 |
| visual refresher | 84045 |
| paper_only | true |

---

## C. Tests

Pre-restart (no OPS restart on failure):

| Suite | Result |
| ----- | ------ |
| `test_vis0b_canonical_trading_risk_ops_adapter` + OPS1B + patch4.2 | **66 passed** |
| manager risk-related (`-k 'risk or portfolio or open_risk or sizing or gate'`) | **5 passed** |

Note: dirty working-tree `OpsDashboard.tsx` breaks unrelated `test_46_dashboard_visual_design_preserved` — not part of VIS0B commit; deselected for activation gate.

---

## D. Baseline

Before restart (`ops_risk_before.json`):

| Field | OPS | Manager |
| ----- | --: | ------: |
| gross / reserved | **0.0** | **1000.0** |
| available | **1000.0** | **0.0** |
| open | 4 | 4 |
| per-TF risk | 0.0 × 4 | 250 × 4 |

`mismatch_reproduced = true` → not `VIS0C_ALREADY_ACTIVE`.

---

## E. OPS Launch Contract

| Field | Value |
| ----- | ----- |
| old PID | 28285 |
| cwd | `/Users/fontecrypto/btc-ml` |
| argv | `venv/bin/python3 dashboard/backend/run_api.py` |
| listen | `0.0.0.0:8080` |
| env | `BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE=1`, `BTC_ML_VOLUME_LOCALIZATION_LIVE=1` |
| pid file | `run/ops_api.pid` (cleared then rewritten) |
| log | `logs/ops_api_vis0c_activation.log` |
| start_new_session | true |

First spawn used `Path(...).resolve()` → Frameworks Python without venv site-packages → `ModuleNotFoundError: uvicorn` (exited immediately). Same activation completed with **non-resolved** `venv/bin/python3` shim (same OPS1C lesson). Counted as one intentional restart completion, not a second activation attempt after a healthy OPS.

---

## F. Old / New OPS PID

| | PID |
| - | --- |
| old | 28285 (stopped) |
| new | **2502** |
| process count | **1** (`Python dashboard/backend/run_api.py`) |
| intentional restarts | 1 |
| duplicate starts | 0 |

---

## G. Aggregate Risk

| Field | Live OPS | Manager | Parity |
| ----- | -------: | ------: | -----: |
| max_risk_usd | 1000 | 1000 | 100% |
| reserved_open_risk_usd | 1000 | 1000 | 100% |
| available_risk_usd | 0 | 0 | 100% |
| risk_utilisation_pct | 100 | — | — |
| open_positions | 4 | 4 | 100% |
| risk_status | AVAILABLE | — | — |
| risk_source | `portfolio_summary.json` | same artifact | — |

---

## H. Per-Timeframe Risk

| TF | reserved | status | source |
| -- | -------: | ------ | ------ |
| M15 | 250 | AVAILABLE | `manager_portfolio_summary.traders[].open_risk_usd` |
| M30 | 250 | AVAILABLE | same |
| H1 | 250 | AVAILABLE | same |
| H4 | 250 | AVAILABLE | same |

No `open + missing → 0`.

---

## I. Missing-Value Semantics

Adapter helpers (post-activation):

| Case | value | status |
| ---- | ----: | ------ |
| flat zero | 0.0 | `ZERO_CONFIRMED` |
| missing aggregate | null | `SOURCE_UNAVAILABLE` |
| stale | null | `SOURCE_STALE` |
| unsupported TF attribution | null | `ATTRIBUTION_UNAVAILABLE` |

---

## J. Frontend Verification

| Check | Result |
| ----- | ------ |
| API payload for UI | `$1000 / $1000`, available `$0`, open 4, TF `$250` |
| Browser fetch (no abort) | same values |
| Vite Live Operations UI | remained **offline fallback** after downtime |
| Root cause | `softFetchOpsSnapshot(timeoutMs=1500)` aborts under browser load; reconnect poll never upgrades |
| Schema break | **false** |
| Deferred | `VIS0B_FRONTEND_SEMANTICS_FOLLOWUP_REQUIRED` + soft-fetch reconnect timeout follow-up |

No frontend code changes in VIS0C.

---

## K. Polling Cycles

Same OPS PID **2502**; `generated_at` advanced; parity 100%; errors empty.

| Field | Poll 1 | Poll 2 | Poll 3 |
| ----- | ------ | ------ | ------ |
| OPS PID | 2502 | 2502 | 2502 |
| generated_at | 10:49:29Z | 10:49:33Z | 10:49:36Z |
| max / reserved / available | 1000 / 1000 / 0 | same | same |
| open | 4 | 4 | 4 |
| M15–H4 | 250 | 250 | 250 |
| risk_source | portfolio_summary | same | same |
| errors | [] | [] | [] |

---

## L. Natural M15-Bar Gate

| Field | Value |
| ----- | ----- |
| baseline tip | `2026-07-27 10:30:00+00:00` |
| accepted tip | `2026-07-27 10:45:00+00:00` |
| accepted_at | `2026-07-27T11:00:13Z` |
| core PIDs | unchanged |
| OPS PID | 2502 unchanged |
| risk transition parity | **100%** |

---

## M. Core Preservation

| Process | Before | After |
| ------- | -----: | ----: |
| pipeline | 4618 | 4618 |
| manager | 61283 | 61283 |
| M15–H4 | 61284–61287 | same |
| visual refresher | 84045 | 84045 |
| OPS API | 28285 | **2502** |

---

## N. Trading Impact

```text
manager/trader source changes during activation = 0
OPS-caused trading writes = 0
entry gate / sizing untouched
```

Only natural book tip advance (M15 bar) observed.

---

## O. Rollback Status

**Not performed.** All activation gates passed.

---

## P. Git / Documentation

Docs-only commit:

```text
docs: record canonical OPS risk activation
```

```text
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

---

## Q. Compliance

```text
production source changes during activation = 0
test changes during activation = 0
pipeline restarts = 0
manager restarts = 0
trader restarts = 0
visualizer restarts = 0
frontend restarts = 0
OPS API intentional restarts = 1
OPS API duplicate starts = 0
OPS-caused trading writes = 0
```

---

## R. Next Step

```text
VIS1A — canonical PnL and trade-history reconciliation
```

Do not change charts yet. Optional deferred: raise `softFetchOpsSnapshot` timeout / reconnect so Vite UI recovers after OPS-only restarts.

---

## Final status

```text
VIS0_CANONICAL_RISK_TRUTH_ACTIVATED
```
