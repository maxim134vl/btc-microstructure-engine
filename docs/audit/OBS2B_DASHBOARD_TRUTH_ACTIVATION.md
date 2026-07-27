# OBS2B — Dashboard Truth Live Activation

**Status:** `OBS2_DASHBOARD_TRUTH_LIVE_ACTIVATED`  
**UTC:** 2026-07-27  
**Candidate commit:** `dfbf770` (`fix: show canonical paper trading state in dashboard`)  
**Branch:** `memory/canonical-system`  
**Pipeline:** PID `4618` (unchanged)  
**Evidence:** `data/quarantine/architecture_recovery/obs2b/20260727_080913/`

---

## A. Result

Live context visualizer now serves canonical paper-trading truth from TF books + lifecycle episode plane.

| Gate | Result |
| ---- | ------ |
| 4 OPEN positions | pass |
| ALL/M15/M30/H1/H4 filters | pass |
| episode 885 continuous band | pass |
| Active trading context = LONG_CONTEXT | pass |
| shadow OBSERVE = diagnostics only | pass |
| 3 refresh cycles same PID | pass |
| 1 natural M15 bar (07:45→08:00) | pass |

---

## B. Core Runtime Health

| Process | PID | Before | After |
| ------- | --: | ------ | ----- |
| pipeline | 4618 | alive | alive |
| manager | 61283 | alive | alive |
| trader M15 | 61284 | alive | alive |
| trader M30 | 61285 | alive | alive |
| trader H1 | 61286 | alive | alive |
| trader H4 | 61287 | alive | alive |
| viewer :8765 | 1193 | alive | alive (not restarted) |

Canonical books at activation: 4× OPEN LONG (unchanged hashes through activation).  
Lifecycle tip advanced 07:45 → 08:00; episode **885** / **LONG_CONTEXT** carried.

Pipeline steps remain **26** (PID 4618 continuous).

---

## C. Source Scope

```text
production source changes during activation = 0
```

No edits to `trading_truth.py`, generator, refresher, `index.html`, `lifecycle_app.js`, or tests.

---

## D. Tests

| Suite | Result |
| ----- | ------ |
| `tests/test_obs2a_dashboard_truth_candidate.py` | 16 passed |
| frontend/UTC/overlay contracts (relevant) | passed |
| `test_context_visual_uses_paper_action_timestamp` (with `PYTHONPATH=scripts/live`) | 2 passed |

Relevant failed tests = **0**.

---

## E. Visual-Refresher Launch Contract

| Field | Value |
| ----- | ----- |
| Script | `scripts/live/run_market_context_visual_refresher.py --interval-seconds 20` |
| Approved launcher | `scripts/ops/start_visual_refresher_detached.py` |
| PID file | `runtime_context_visual_refresher.pid` |
| Lock | `runtime_context_visual_refresher.lock` |
| Log | `logs/context_visual_refresher.log` |
| cwd | `/Users/fontecrypto/btc-ml` |
| Loads Python modules | at process start only → restart required |

---

## F. Old / New Visual-Refresher PID

| | PID |
| --- | ---: |
| Old | 5105 |
| New | 84045 |
| Count after | 1 |
| Duplicate starts | 0 |

---

## G. Vite / Frontend Asset Contract

Context visualizer is served by Python viewer `:8765` from `apps/context_visualizer/public` with `Cache-Control: no-store`.

| Asset | Served = disk | Notes |
| ----- | ------------- | ----- |
| `index.html` | yes | TF selector + truth banner present |
| `lifecycle_app.js` | yes | |
| `trading_truth.json` | yes | open=4, ep=885 |

OPS Vite (`dashboard/frontend`, PID 66359) is unrelated → **Vite intentional restart = 0**.

---

## H. Pre-Activation Snapshot

Quarantine: `data/quarantine/architecture_recovery/obs2b/20260727_080913/`

| Artifact | Pre state |
| -------- | --------- |
| `trading_truth.json` | missing |
| `open_positions.json` | count **0** |
| `lifecycle_context_episodes.json` | max episode **744**, bands885=0 |

---

## I. First Refresh

`generated_at=2026-07-27T08:10:12.267564Z`

| Field | Value |
| ----- | ----: |
| open positions | 4 |
| timeframes | M15,M30,H1,H4 |
| active episode | 885 |
| active state | LONG_CONTEXT |
| bands885 | 1 |
| shadow primary | false |

---

## J. Trading-Truth JSON

Contract present: `generated_at`, `canonical_tips`, `active_episode`, `lifecycle_state`, `manager_decision`, `open_positions`, `closed_trades`, `timeframes`, `data_quality`.

| Check | Value |
| ----- | ----- |
| paper_only | true |
| execution_enabled | false |
| positions_source_fresh | true |
| episodes_source_fresh | true |
| missing_sources | [] |
| position parity | 100% |
| episode parity | 100% |
| timestamp epoch parity | 100% |

---

## K. Open Positions

4 rows; exits null; duplicate IDs = 0; source `data/trading/timeframe_traders`.

| TF | Entry UTC | Price |
| -- | --------- | ----: |
| M15 | 2026-07-26T20:45:00Z | 64662.72 |
| M30 | 2026-07-26T20:45:00Z | 64662.72 |
| H1 | 2026-07-26T21:15:00Z | 64698.10 |
| H4 | 2026-07-27T00:15:00Z | 65227.32 |

---

## L. Timeframe Filters

Browser CDP verified:

| Filter | Open |
| ------ | ---: |
| ALL | 4 |
| M15 | 1 |
| M30 | 1 |
| H1 | 1 |
| H4 | 1 |

`?tf=` + `localStorage` persistence confirmed; no full reload.

---

## M. Active Episode

Dashboard active episode = **885** / **LONG_CONTEXT** (lifecycle memory plane).

---

## N. Episode Bands

885 carry rows → **1** continuous active band; visual end = latest lifecycle evaluation tip.

---

## O. Shadow Context Separation

UI: `Active trading context · ep 885` + `shadow diag OBSERVE`  
JSON: `shadow_diagnostics.is_active_trading_context = false`  
Primary leak = **0**.

---

## P. Truth Banner

Live browser:

```text
Trading runtime: LIVE PAPER · Real execution: DISABLED · Pipeline: HEALTHY
· TF ALL · open 4 · … · ep 885 · Dashboard lag 0s
```

`STALE DATA = false` while sources fresh.

---

## Q–R. Position / Stop-Take Overlays

Entry markers match canonical timestamps/prices (epoch + price parity 100%).  
Stop/TP present per TF from book metadata; null would omit lines without hiding positions.

---

## S. Three Refresh Cycles

Same PID **84045**; `generated_at` advanced three times; open=4; bands885=1; shadow leak=0; parity 100%.

Evidence: `meta/three_refresh_cycles.json`.

---

## T. Natural M15-Bar Gate

| Field | Value |
| ----- | ----- |
| baseline tip | 2026-07-27 07:45:00Z |
| new feed tip | 2026-07-27 08:00:00Z |
| new lifecycle tip | 2026-07-27 08:00:00Z |
| pipeline | 4618 |
| refresher | 84045 |
| episode | 885 carried |
| open | 4 |
| active band | 1 |

Evidence: `meta/natural_m15_bar_gate.json`.

---

## U. UI Verification Matrix

| Surface | Expected | Actual | Result |
| ------- | -------- | ------ | ------ |
| Truth banner | LIVE PAPER | LIVE PAPER | pass |
| Real execution | DISABLED | DISABLED | pass |
| Active context | LONG_CONTEXT | LONG_CONTEXT | pass |
| Active episode | 885 | 885 | pass |
| Episode bands | 1 continuous | 1 | pass |
| ALL positions | 4 | 4 | pass |
| M15/M30/H1/H4 | 1 each | 1 each | pass |
| Shadow status | diagnostics only | shadow diag OBSERVE | pass |
| Closed empty (H4) | explicit | “No closed trades for selected timeframe” | pass |

---

## V. Core / Trading Safety

```text
core deliberate restarts = 0
manager deliberate restarts = 0
trader deliberate restarts = 0
dashboard-caused trading-book writes = 0
```

Position book SHA256 unchanged for M15/M30/H1/H4 through activation + natural bar gate.

---

## W. Git / Gitea

Docs-only commit after acceptance: `docs: record canonical dashboard truth activation`  
Gitea push: **NOT PERFORMED** (remote ENOSPC)  
GitHub push: **NOT PERFORMED**

---

## X. Compliance

```text
production source changes during activation = 0
pipeline restarts = 0
manager restarts = 0
trader restarts = 0
visual-refresher intentional restarts = 1
Vite intentional restarts = 0
dashboard JSON writes = allowed
trading-book writes caused by dashboard = 0
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

---

## Y. Next Step

Observe dashboard + paper-trading stability.  
Do not start new architectural fixes until stability observation completes.
