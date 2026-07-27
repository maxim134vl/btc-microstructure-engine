# OBS2A — Dashboard Truth Restoration Candidate

**Status:** `OBS2A_DASHBOARD_TRUTH_CANDIDATE_READY`  
**UTC:** 2026-07-27  
**HEAD (pre-commit base):** `3db363a` (`memory/canonical-system`)  
**Pipeline:** PID `4618` (unchanged; not restarted)  
**Prior audit:** `docs/audit/OBS1_DASHBOARD_PAPER_TRADING_TRUTH_AUDIT.md`  
**Candidate artifacts:** `data/candidate/architecture_recovery/obs2a_dashboard_truth_candidate/`

---

## A. Result

Isolated dashboard/visualizer candidate restores decision-driving paper truth:

- 4 canonical OPEN positions (M15/M30/H1/H4)
- continuous live episode band for `885`
- timeframe selector `ALL/M15/M30/H1/H4`
- shadow arbitration marked diagnostics-only

Live dashboard / pipeline / traders not restarted. No trading-book writes.

---

## B. Canonical Position Sources

| TF | Book root | signals | orders | fills | trades | positions | Status | Side | Entry time (UTC) | Entry price |
| -- | --------- | ------- | ------ | ----- | ------ | --------- | ------ | ---- | ---------------- | ----------: |
| M15 | `data/trading/timeframe_traders/M15/` | ✓ | ✓ | ✓ | ✓ | ✓ | OPEN | LONG | 2026-07-26T20:45:00Z | 64662.72 |
| M30 | `data/trading/timeframe_traders/M30/` | ✓ | ✓ | ✓ | ✓ | ✓ | OPEN | LONG | 2026-07-26T20:45:00Z | 64662.72 |
| H1 | `data/trading/timeframe_traders/H1/` | ✓ | ✓ | ✓ | ✓ | ✓ | OPEN | LONG | 2026-07-26T21:15:00Z | 64698.10 |
| H4 | `data/trading/timeframe_traders/H4/` | ✓ | ✓ | ✓ | ✓ | ✓ | OPEN | LONG | 2026-07-27T00:15:00Z | 65227.32 |

Adapter: `apps/context_visualizer/trading_truth.py` (`load_open_positions`, `load_closed_trades`) — read-only.

---

## C. Canonical Episode Source

Decision-driving plane (not shadow):

```text
market_context_lifecycle_memory.parquet  (active tip → episode 885, LONG_CONTEXT)
market_context_lifecycle_episodes.parquet (carry rows collapsed → one band)
```

Collapse algorithm (`collapse_lifecycle_episodes`): group by `episode_id`, earliest start, explicit end or latest evaluation tip for open episodes.

Shadow `auction_context_arbitration_memory` exposed only as `shadow_diagnostics` with `is_active_trading_context=false`.

---

## D. Existing Dashboard Sources

| Role | Source file | Function / component | Input | Output | Consumer |
| ---- | ----------- | -------------------- | ----- | ------ | -------- |
| Visual refresher | `scripts/live/run_market_context_visual_refresher.py` | refresh loop | lifecycle + TF books | `public/data/*.json` | static visualizer |
| Lifecycle generator | `apps/context_visualizer/generate_lifecycle_context_data.py` | `build_episode_rows` | lifecycle episodes parquet | `lifecycle_context_episodes.json` | chart bands |
| Truth adapter | `apps/context_visualizer/trading_truth.py` | `build_trading_truth` | TF books + lifecycle | `trading_truth.json` / `open_positions.json` | frontend + refresher |
| Frontend chart | `apps/context_visualizer/public/lifecycle_app.js` | `renderChart` / overlays | candles + shapes | canvas | browser |
| TF selector | `index.html` `#timeframeSelect` + JS filter | user selection | URL/`localStorage` | filtered overlays | chart/panels |
| Truth banner | `#truthBanner` | `updateTruthBanner` | `trading_truth.json` | LIVE PAPER / lag / STALE | header |

---

## E. Root Causes (confirmed in OBS1, fixed in candidate)

1. **Open positions empty** — visual layer read research `paper_simulator` / closed-only normalized trades; ignored `data/trading/timeframe_traders/*/positions.parquet`.
2. **Episode bands stale** — policy/research export overwrote primary `lifecycle_context_episodes.json`; carry rows for 885 not collapsed to one continuous band.
3. **M15-only trades UX** — no TF selector; overlays not filtered/labeled by timeframe.

---

## F. Backend Changes

| File | Change |
| ---- | ------ |
| `apps/context_visualizer/trading_truth.py` | **new** read adapter + `/dashboard/trading-truth` equivalent JSON writer |
| `apps/context_visualizer/generate_lifecycle_context_data.py` | episode collapse via adapter |
| `scripts/live/run_market_context_visual_refresher.py` | stop policy overwrite of primary bands; wire TF open positions + `trading_truth.json` |

---

## G. Frontend Changes

| File | Change |
| ---- | ------ |
| `public/index.html` | TF selector ALL/M15/M30/H1/H4; truth banner |
| `public/lifecycle_app.js` | load `trading_truth` / `open_positions`; separate open vs closed; TF filter + URL state; empty-state copy; Active trading context vs shadow diag |

---

## H. Timeframe Support

`ALL | M15 | M30 | H1 | H4` — selector in UI, filter in JS, backend `timeframe` argument on adapter. Candles remain M15 feed (unchanged); overlays/positions filtered by TF.

---

## I. Open Positions

API/adapter returns 4 OPEN rows with `position_id`, `timeframe`, `status`, `side`, `entry_timestamp`, `entry_price`, `quantity`, `notional`, `stop_price`, `take_profit_price`, `unrealized_pnl` (null if absent), `episode_key`. Missing exits → `null`, rows not dropped.

---

## J. Closed Trades

Loaded separately from TF `trades.parquet` (requires `exit_ts`). Open positions never classified as closed. Empty closed list shows: “No closed trades for selected timeframe” while open count remains visible.

---

## K. Episode Bands

Episode `885`: 27 carry rows → **1** continuous band; `is_active=true`; end = latest lifecycle evaluation tip for visual span only (artifact unchanged).

---

## L. Shadow Context Separation

Policy export → `shadow_policy_context_episodes.json` / diagnostics only. UI labels primary plane “Active trading context”; shadow tip shown as `shadow diag …`, never as active trading context.

---

## M. UTC Contract

All adapter timestamps timezone-aware UTC (`…Z`). Matching uses UTC epoch; display may localize; banner/status note UTC. Epoch shift = 0 in snapshot parity.

---

## N. Candidate Snapshot

`data/candidate/architecture_recovery/obs2a_dashboard_truth_candidate/dashboard_truth_snapshot.json`

| Metric | Value |
| ------ | ----: |
| position parity | 100% |
| episode parity | 100% |
| timeframe parity | 100% |
| timestamp epoch parity | 100% |

Also: `trading_truth.json`, `open_positions.json`, collapsed `lifecycle_context_episodes.json` (candidate copy only).

---

## O. Backend Tests

`tests/test_obs2a_dashboard_truth_candidate.py` — 16 passed (open×4, TF filters, episode 885, shadow separation, UTC, no book writes).

---

## P. Frontend Tests

Same file — selector/banner/wiring string contracts; open vs closed separation; stale/empty-state copy.

---

## Q. Regression Tests

Lifecycle candle/episode load paths preserved; `test_context_visual_trade_position_overlay` UI geometry comment restored; M15 closed trades path still readable via normalized/closed layers.

---

## R. Production Scope

| Path | Kind |
| ---- | ---- |
| `apps/context_visualizer/trading_truth.py` | new |
| `apps/context_visualizer/generate_lifecycle_context_data.py` | modified |
| `scripts/live/run_market_context_visual_refresher.py` | modified |
| `apps/context_visualizer/public/index.html` | modified |
| `apps/context_visualizer/public/lifecycle_app.js` | modified |

**Production files changed = 5.** Core/manager/traders/books = 0.

---

## S. Git Commit

Local commit: `fix: show canonical paper trading state in dashboard`  
Gitea push: **NOT PERFORMED**  
GitHub push: **NOT PERFORMED**

---

## T. Compliance

```text
core architecture changes = 0
manager changes = 0
trader changes = 0
trading-book changes = 0
pipeline restarts = 0
manager/trader restarts = 0
live dashboard restarts = 0
live writes = 0
paper-trading writes caused by task = 0
local commit = 1
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

---

## U. Next Step

**OBS2B — controlled dashboard-only activation** (after candidate acceptance).  
Do not restart core runtime.
