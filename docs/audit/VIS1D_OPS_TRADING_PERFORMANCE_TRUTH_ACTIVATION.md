# VIS1D — OPS Trading Performance Truth Activation

**Status:** `VIS1D_API_ACTIVATED_UI_RECONNECT_DEFECT`  
**UTC quarantine:** `20260727_115520`  
**Branch:** `memory/canonical-system`  
**Activated commit:** `66aeeb6` (`feat: expose canonical trading performance in OPS`)  
**Quarantine:** `data/quarantine/architecture_recovery/vis1d/20260727_115520/`  
**Mode:** `paper_only=true` · real execution disabled

Backend activation gates (parity, polls, natural M15 bar, risk preservation) **passed**.  
Vite Live Operations UI remained on offline soft-fetch fallback after OPS downtime — **do not roll back backend**. Follow-up: `OPS_SOFT_FETCH_RECONNECT_FIX` before VIS2A.

---

## A. Result

One controlled OPS API-only restart loaded VIS1C wiring. Live `/api/v1/ops/snapshot` → `runtime_truth.trading_operations.performance` is sourced from:

```text
src/btc_ml/trading/trading_performance_truth.py
mtm_basis = GROSS_UNREALISED
```

Same-mark portfolio / per-TF / fees / equity / sample / data-quality parity = **100%**.  
VIS0 risk truth preserved. Core/trader PIDs unchanged. Visualizer untouched.

UI hard refresh still shows `LIVE DATA UNAVAILABLE` while API returns 200 + canonical PnL → status above.

---

## B. Preflight

| Check | Result |
| ----- | ------ |
| branch | `memory/canonical-system` |
| HEAD | `66aeeb6` |
| pipeline | 4618 |
| OPS API (old) | 2502 |
| manager | 61283 |
| traders | 61284–61287 |
| visual refresher | 84045 |
| live feed | 93404 |

---

## C. Tests

Pre-restart (no OPS restart on failure):

| Suite | Result |
| ----- | ------ |
| VIS1C + VIS1B + VIS0B + OPS1B + patch4.2 | **86 passed** |

---

## D. Baseline

Before restart, live HTTP OPS **lacked** `trading_operations` (old process). Risk already VIS0-correct. Realised/unrealised present via old book/manager path; fees/sample/data-quality **not** exposed.

Canonical pre-activation sample (dynamic): closed **8**, open **3**, realised net ≈ **200.33**, unrealised gross dynamic, fees ≈ **122.06**.

---

## E. OPS Launch Contract

| Field | Value |
| ----- | ----- |
| cwd | `/Users/fontecrypto/btc-ml` |
| argv | `venv/bin/python3 dashboard/backend/run_api.py` (**no** `.resolve()`) |
| listen | `0.0.0.0:8080` |
| env | `BTC_ML_VOLUME_LOCALIZATION_LIVE=1`, `BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE=1` |
| pid file | `run/ops_api.pid` |
| log | `logs/ops_api_vis1d_activation.log` |
| start_new_session | true (required; first nohup spawn exited with parent shell) |

First spawn without `start_new_session` died after parent exit — counted as same intentional activation completion (VIS0C/OPS1C pattern), not a second healthy restart.

---

## F. Old / New OPS PID

| | PID |
| - | --- |
| old | 2502 (stopped) |
| new (final) | **48835** |
| process count | **1** |
| intentional restarts | 1 |
| duplicate starts | 0 |

---

## G. Canonical Performance Source

Live `trading_operations.performance.source`:

| Field | Value |
| ----- | ----- |
| adapter | `src/btc_ml/trading/trading_performance_truth.py` |
| schema_version | `trading_performance_truth_v1` |
| mark_source | `manager.portfolio_summary.mark_price` |
| mtm_basis | `GROSS_UNREALISED` |
| excluded | RESEARCH / LEGACY / DASHBOARD / QUARANTINE |

Old OPS calculator active = **false**.

---

## H. Portfolio Performance

Same-mark live parity **100%** (values dynamic; not hardcoded):

| Field | Gate |
| ----- | ---- |
| closed / open counts | 100% |
| realised gross/net | 100% |
| unrealised gross/net | 100% |
| total gross/net | 100% |
| fees / slippage | 100% |
| equity (initial/closed/MTM) | 100% |
| frontend aliases realized/unrealized | 100% |

Natural activity during activation advanced counts (e.g. closed 8→9) — OPS tracked adapter state.

---

## I. Per-Timeframe Performance

M15/M30/H1/H4 closed/open/realised/unrealised/fees/slippage/tips parity **100%**.  
Process side/alive and reserved risk retained separately.  
Episode **743**: M15+M30+H1 distinct entities; `duplicate_count=0`; `VALID_MULTI_TF_POSITIONS`.

---

## J. Fees / Slippage

Portfolio + per-TF from adapter only; parity **100%**.

---

## K. Equity

`initial_equity_usd` / `closed_equity_usd` / `mark_to_market_equity_usd` from adapter; parity **100%**.

---

## L. Sample / Metric Statuses

| Metric | Live |
| ------ | ---- |
| sample_status | PRELIMINARY |
| profit factor / expectancy | PRELIMINARY |
| Sharpe | null / INSUFFICIENT_SAMPLE |
| Calmar | null / INSUFFICIENT_HISTORY |
| annualised return | null / INSUFFICIENT_HISTORY |
| NaN / Infinity | **false** |

---

## M. Research / Legacy Exclusions

`excluded_research_count=11`, `excluded_legacy_count=4`.  
`closed_trade_count` = canonical only (not inflated by 11+4).

---

## N. Risk Preservation

Manager vs OPS: max / reserved / available / per-TF reserved = **100%**.  
`risk_semantics=reserved_open_risk`. Performance does not replace risk.

---

## O. Section Isolation

Candidate/tests: performance failure → `section_errors.trading_performance`, aliases null, other sections preserved.  
Live healthy payload: `section_errors.trading_performance` **absent**.

---

## P. Frontend Verification

| Check | Result |
| ----- | ------ |
| API aliases for UI | canonical realised/unrealised present |
| Browser hard refresh (`5173/?nocache=vis1d`) | **offline fallback** |
| Schema crash | false |
| Classification | `VIS1D_API_ACTIVATED_UI_RECONNECT_DEFECT` |
| Follow-up | `OPS_SOFT_FETCH_RECONNECT_FIX` |

Same softFetch reconnect defect noted in VIS0C.

---

## Q. Three Polling Cycles

Same OPS PID **48835**; `generated_at` advances across polls; performance errors = 0.

Post-bar example:

| Poll | generated_at |
| ---- | ------------ |
| 1 | 2026-07-27T12:01:02Z |
| 2 | 2026-07-27T12:01:06Z |
| 3 | 2026-07-27T12:01:10Z |

---

## R. Natural M15-Bar Gate

| Field | Value |
| ----- | ----- |
| baseline context tip | 2026-07-27T11:30:00Z |
| accepted tip | 2026-07-27T11:45:00Z |
| accepted_at | 2026-07-27T12:00:26Z |
| reasons | safe_upstream_tip, final_context_tip, candle_max |
| core/OPS PIDs | unchanged |
| post-bar parity | 100% |
| risk | preserved |

---

## S. Core Process Preservation

```text
pipeline 4618, manager 61283, traders 61284–61287, refresher 84045, feed 93404
OPS 48835
all unchanged after activation
```

---

## T. Trading Non-Impact

No manager/trader/book schema edits. OPS restart created no signals/orders/fills/trades/positions/commands. Natural live book advances only.

Visualizer process/files/Detailed PnL unchanged (deferred to VIS2A).

---

## U. Git / Documentation

Docs-only commit:

```text
docs: record OPS performance truth activation
```

Gitea/GitHub push: **NOT PERFORMED**.  
Production/test source changes during activation: **0**.

---

## V. Compliance

```text
OPS API intentional restarts = 1
duplicate starts = 0
pipeline/manager/trader/visualizer restarts = 0
source changes during activation = 0
OPS-caused trading writes = 0
pushes = 0
```

---

## W. Next Step

1. **`OPS_SOFT_FETCH_RECONNECT_FIX`** — narrow Vite softFetch reconnect after OPS downtime.  
2. Then **`VIS2A` — four native timeframe charts functional audit** (sources/contracts first; no chart implementation until audit).

Do **not** treat UI reconnect defect as reason to revert `66aeeb6`.
