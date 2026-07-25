# PATCH 4.3 — Trade Chart Runtime Truth Audit and Parity Contract

**Status:** `PATCH4_TRADE_CHART_PARITY_CONTRACT_READY`  
**Branch:** `memory/canonical-system`  
**Phase:** audit + contract only — **no chart activation**, no trading semantics changes, no visual redesign.

## A. Result

Trade chart is visually live, but its closed-trade render plane is **not** bound to the repaired production paper ledger.

Primary active source:

```text
data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet
→ normalized_trade_render_layer
→ paper_trade_overlays.json
```

Production ledger remains:

```text
paper_signals / paper_orders / paper_trades / paper_positions
```

Exact trade-id intersection between chart and production CTRL ledger: **0**.  
All divergences are explained. Unexplained = **0**.

## B. Scope Preserved

Unchanged by this patch:

- feed / pipeline / context refresher / paper controller
- paper ledger bytes
- trading flags (`CONTINUATION=0`, `PRICE_GATE=OFF`, execution/exchange disabled)
- chart CSS / theme / fonts / layout / library
- no Patch 4.4/5 activation
- no commit/push

## C. Chart Surface Inventory

| Layer | Path | Role |
| --- | --- | --- |
| Frontend | `apps/context_visualizer/public/{index.html,lifecycle_app.js,lifecycle.css}` | Production trade chart UI |
| Public read-model | `apps/context_visualizer/public/data/*` | JSON consumed by FE |
| Generator | `scripts/live/run_market_context_visual_refresher.py` | Visual-only refresher |
| Raw ledger builder | `scripts/live/visual_paper_trade_overlay_builder.py` | Can build from paper_*.parquet |
| Legacy export | `scripts/research/export_policy_context_visual_data.py` | Policy-context visual export (`LATEST_CONTEXT_ID=721`) |

Frontend loads: candles, overlays, normalized layer, pnl, visual status, controller cycles.  
Frontend does **not** load `paper_signals` / `paper_orders` marker planes.

## D. Production Ledger Truth

| Dataset | Rows | Notes |
| --- | ---: | --- |
| paper_signals | 10 | CTRL + history |
| paper_orders | 12 | FILLED paper orders |
| paper_trades (fills) | 12 | point-in-time fills |
| paper_positions | 7 | all CLOSED |
| CTRL closed positions | 4 | canonical production closed set |
| ONE_SHOT positions | 3 | non-primary for CTRL chart truth |
| open positions | 0 | |

CTRL closed net P&L (sum `position.realized_pnl`) ≈ **-80.86 USD**.

Duplicates: signals/orders/trades/positions = **0**.

## E. Current Chart Truth

| Metric | Value |
| --- | --- |
| rendered closed overlays | 11 |
| trade ids | `POLICY_CONTEXT_CANONICAL_BAR_TRADE_*` |
| `PAPER_TRADE_*` on chart | 0 |
| `controller_ledger_used_for_render` | **false** |
| controller overlay count | 0 |
| chart net PnL (`pnl_summary`) | ≈ **+1672.59 USD** |
| signal markers | absent |
| order markers | absent |

## F. Root Cause

1. `refresh_once()` builds overlays exclusively from  
   `build_normalized_trade_render_layer()` ← policy-context parquet.
2. `merge_live_open_positions_into_policy_overlays()` exists to merge controller ledger shapes, but is **never called** (dead code).
3. PnL/cards therefore follow visual economics of policy-context trades, not repaired CTRL positions.
4. Signal/order marker plane was never wired into `lifecycle_app.js`.

## G. Parity Matrix (summary)

| Check | Result | Classification |
| --- | --- | --- |
| Primary ID namespace | FAIL | SOURCE_MISMATCH |
| CTRL closed count vs chart paper ids | FAIL | COUNT_MISMATCH |
| CTRL PnL vs chart PnL | FAIL | ECONOMICS_MISMATCH |
| `controller_ledger_used_for_render` | FAIL | CONTRACT_VIOLATION |
| Signal markers | FAIL | MISSING_LAYER |
| Order markers | FAIL | MISSING_LAYER |
| Merge helper active | FAIL | DEAD_CODE |
| ID intersection | FAIL | ZERO_INTERSECTION |
| Ledger duplicate fills | PASS | LEDGER_OK |
| Unexplained | **0** | — |

Full CSV: `data/research/patch4_3_trade_chart_parity.csv`.

## H. Candidate Contract

Artifact: `data/research/patch4_3_candidate_trade_chart.json`

Required production chart source hierarchy:

1. production paper ledger (`paper_positions` + fills/orders/signals)
2. canonical market feed / lifecycle candles
3. context lifecycle + decision log (lineage only)
4. paper controller state (process health / no-trade)

Forbidden as primary truth:

- `policy_context_canonical_bar_policy_trades.parquet`
- hardcoded `LATEST_CONTEXT_ID`
- dead merge assumptions
- restated synthetic IDs as primary closed set

Candidate closed trades: **4** CTRL positions with:

- entry/exit timestamps & prices from ledger
- quantity / fees / slippage / gross / net
- exit/trade reason
- context episode lineage from position metadata
- linked signal/order snapshots when parent ids exist

Signals/orders/fills included as first-class entities with `should_render_marker=true`.

ONE_SHOT rows classified legacy/non-primary.

## I. Visual Preservation

No frontend HTML/CSS/JS visual edits in Patch 4.3.  
Baseline hashes recorded in `data/research/patch4_3_visual_baseline_<tag>.json`.

Expected standing rule for next activation phase:

```text
данные и bindings меняются
визуальная система остаётся прежней
```

## J. Safety

- Audit script read-only
- No paper/cognition/feed writes
- No exchange/execution
- No model-runtime restart
- No chart activation

## K. Artifacts

- `data/research/patch4_3_preflight_<tag>.json`
- `data/research/patch4_3_chart_inventory.json`
- `data/research/patch4_3_ledger_inventory.json`
- `data/research/patch4_3_trade_chart_parity.csv`
- `data/research/patch4_3_runtime_status_gaps.json`
- `data/research/patch4_3_frontend_audit.json`
- `data/research/patch4_3_candidate_trade_chart.json`
- `data/research/patch4_3_candidate_trade_chart.meta.json`
- `data/research/patch4_3_current_vs_candidate_<tag>.json`
- `data/research/patch4_3_visual_baseline_<tag>.json`
- `data/research/patch4_3_summary_<tag>.json`
- `scripts/ops/patch4_3_trade_chart_runtime_truth_audit.py`
- `tests/test_patch4_3_trade_chart_runtime_truth_audit.py`

## L. Acceptance for this phase

```text
audit_only = true
activation_performed = false
frontend_visual_changes = 0
unexplained_divergences = 0
candidate_closed_trades = 4
controller_ledger_used_for_render_current = false
parity_contract_ready = true
```

## M. Next Step

Separate activation patch (not started) must:

1. switch primary closed/open render source to production ledger
2. wire or replace dead merge path
3. expose signal/order marker data without redesign
4. make chart PnL match CTRL ledger economics
5. keep CSS/theme/layout unchanged
6. keep model runtime untouched

Do **not** auto-start activation.
