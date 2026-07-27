# VIS2B — Four Native Timeframe Charts Candidate

**Status:** `VIS2B_FOUR_NATIVE_TIMEFRAME_CHARTS_CANDIDATE_READY`  
**Branch:** `memory/canonical-system`  
**Basis:** `VIS2A_FOUR_NATIVE_TIMEFRAME_CHARTS_ARCHITECTURE_PROVEN`  
**Mode:** `paper_only=true`, real execution disabled

Evidence: `data/candidate/architecture_recovery/vis2b_four_native_timeframe_charts/`

---

## A. Result

Candidate ready: isolated M15/M30/H1/H4 chart truth adapter, gated generator hook (default OFF → no live public write), 2×2 frontend with singular global strip, Detailed PnL + Model Metrics removed. 22 tests green. No process restarts. OPS untouched.

---

## B. Production Scope

| # | File | Role |
| --- | --- | --- |
| 1 | `apps/context_visualizer/timeframe_chart_truth.py` | chart-truth adapter + atomic writer + candidate CLI |
| 2 | `apps/context_visualizer/generate_lifecycle_context_data.py` | gated `emit_timeframe_chart_truth_if_enabled()` |
| 3 | `apps/context_visualizer/public/lifecycle_app.js` | four independent charts + strip |
| 4 | `apps/context_visualizer/public/index.html` | GRID layout + panel removal (+ inline grid CSS) |

Tests (3):

- `tests/test_vis2b_timeframe_chart_truth_candles.py`
- `tests/test_vis2b_timeframe_chart_truth_identity.py`
- `tests/test_vis2b_layout_dom.py`

---

## C. Baseline Visualizer

Captured under `baseline/`: single `#lifecycleCanvas`, ALL-union overlays, CTX suffix identity, Detailed PnL + Model Metrics present.

---

## D. Chart-Truth Adapter

`build_timeframe_chart_truth()` — read-only, deterministic, no side effects until explicit write.

---

## E. Candle Sources

- **M15:** `data/live/live_market_feed.parquet` (native)
- **M30/H1/H4:** `multi_timeframe_availability.build_completed_bars` (canonical; no second aggregator)

---

## F. Aggregation / Timestamps / Confirmed Bars

UTC · BAR_OPEN · close = open + duration · first/max/min/last + volume sum · partial bars excluded.

---

## G. Timeframe States

Per TF: `availability_status`, `directional_state`, `manager_instruction`, `position_side`, `position_status` (not merged into one ambiguous `state`).

---

## H. Global Lifecycle Strip

Collapsed episodes from `market_context_lifecycle_episodes.parquet` + active tip from memory. Rendered once above the grid.

---

## I–J. Trades / Isolation

Only `data/trading/timeframe_traders/{TF}/`. Each chart receives only own TF entities.

---

## K–L. Identity / Episode Association

Primary: `trade_id` / `position_id`. Display: `M15 · <short id>`.  
Episode shown only when `TF:id` namespace matches entity TF **and** temporal overlap with global episode; else `episode_id=null`, `UNPROVEN`.

---

## M–N. Regressions

- **743:** three TF closed entities, one per chart; **not** labeled CTX 743 (UNPROVEN vs global July-8 episode).
- **879 / 881:** entities stay on own TF charts; global episode appears once in strip.

---

## O–P. Stop/Take / Performance Headers

Column → metadata_json → null. Headers read `trading_performance_truth` projection (import only; module not modified).

---

## Q. Payload

Candidate: `candidate/timeframe_chart_truth.json` (+ per-TF / global splits).  
Live `public/data/timeframe_chart_truth.json` **not** written (hook default OFF).

Activation for VIS2C:

```bash
ENABLE_TIMEFRAME_CHART_TRUTH=1
# or TIMEFRAME_CHART_TRUTH_OUT=apps/context_visualizer/public/data/timeframe_chart_truth.json
```

---

## R–T. Layout / Removals

GRID 2×2 · expand single TF · no `#lifecycleCanvas` · Detailed PnL removed · Model Metrics removed · freed space → chart grid.

---

## U–W. Data quality / Tests / Visual

Section isolation on missing TF. 22 passed. Candidate fixture renderable via `?chart_truth=` or candidate path fallbacks in `lifecycle_app.js`.

---

## X. OPS Non-Impact

`/api/v1/ops/snapshot` 200; performance + risk present; no OPS/Vite/core restarts.

---

## Y. Git

One local commit: `feat: add isolated native timeframe charts`  
No Gitea/GitHub push.

---

## Z. Compliance

| Rule | Value |
| --- | --- |
| production files | 4 |
| test files | 3 |
| process restarts | 0 |
| live public chart-truth write | 0 |
| trading / OPS / manager / trader changes | 0 |

---

## AA. Next Step

**VIS2C — controlled visualizer-only activation**

- enable chart-truth emit for refresher/public
- do not restart OPS/Vite/core unless required for visualizer/refresher only
- verify four live charts across refresh cycles and natural M15 / HTF boundaries
