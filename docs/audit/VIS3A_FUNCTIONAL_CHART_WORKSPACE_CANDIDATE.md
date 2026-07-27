# VIS3A — Functional Multi-Timeframe Chart Workspace Candidate

**Status:** `VIS3A_FUNCTIONAL_CHART_WORKSPACE_CANDIDATE_READY`  
**Branch:** `memory/canonical-system`  
**Mode:** `paper_only = true` · real execution disabled  
**Candidate:** `data/candidate/architecture_recovery/vis3a_functional_chart_workspace/`

---

## Baseline (user-confirmed)

Prior live usability claim (`VIS2D_…_PROVEN`) is **rejected**. Baseline defects classified as:

```text
VISUAL_WORKSPACE_ARCHITECTURE_FAILURE
```

- Unequal panels (M15/H1 ≈ 3× M30/H4)
- No usable horizontal pan/scroll of history
- Unreadable trade markers / missing TF historical context
- Useless global lifecycle strip
- OPS frontend does **not** show relocated performance summary

---

## What changed (≤3 production files)

| File | Change |
|---|---|
| `apps/context_visualizer/timeframe_chart_truth.py` | schema `v2`; per-TF `context_segments` from `timeframe_command_memory`; trade isolation assertion → `TF_SOURCE_CONTAMINATION`; candidate dir → vis3a; visual_contract |
| `apps/context_visualizer/public/index.html` | remove global strip; equal `minmax(0,1fr)` grid; nav Reset/Fit/Latest; empty `[hidden]{display:none!important}` |
| `apps/context_visualizer/public/lifecycle_app.js` | pan/zoom/trackpad; viewport persistence; context bands; E/X/OPEN markers; selection; SL/TP off-screen cues |

**Not changed:** manager, traders, books, risk/PnL formulas, `trading_performance_truth.py`, OPS backend/frontend, pipeline, lifecycle producers, `generate_lifecycle_context_data.py`.

---

## TF context history proof

Canonical historical per-TF state exists:

```text
data/trading/manager/timeframe_command_memory.parquet
CommandBus.timeframe_commands(TF)
```

Segments collapse consecutive same `timeframe_state` with fields:

`start/end`, `directional_state`, `availability_status`, `manager_instruction`, `entry_eligibility` (from `action_allowed`), `source=timeframe_command_memory`.

Not built from current snapshot tip alone.

Candidate counts (example): M15 15 · M30 11 · H1 8 · H4 2 segments. Cross-TF contamination = 0.

---

## Workspace contract

- GRID: `repeat(2, minmax(0, 1fr))` × `repeat(2, minmax(0, 1fr))`; panels `min-width/min-height: 0`
- Measured **1440×900:** panels 703×375 equal; **clipped = false**
- Measured **1920:** equal panels
- Global lifecycle strip DOM count = **0**
- Expanded M15/M30/H1/H4 fill available area; return to GRID preserves per-TF viewport state
- Default visible: M15≈144, M30≈96, H1≈96, H4=all loaded; Fit / Reset / Go to latest
- Refresh: if user panned history → preserve range; if at right edge → follow latest

---

## Trades / markers

- Source: `data/trading/timeframe_traders/{TF}/` only
- Runtime assertion on payload; contaminants set `panel_status=TF_SOURCE_CONTAMINATION` and suppress drawing
- Entry = triangle (LONG↑ / SHORT↓); Exit = X; Open = entry + dashed entry/SL/TP + `OPEN` (no exit)
- Closed = entry+exit+connector; selection dims others + detail panel
- No permanent `CTX` / long ID labels on canvas
- SL/TP outside candle autoscale → edge cues `TP ↑` / `SL ↓` (no candle squash)

---

## OPS honesty

```text
backend trading_operations.performance exists
visible OPS frontend relocation is NOT complete
```

Deferred mandatory stage:

```text
OPS3A — VISIBLE TRADING OPERATIONS SUMMARY
```

Portfolio / per-TF / metrics as specified in the VIS3A brief. VIS3A does not claim Detailed PnL / Evaluation Metrics are visible in OPS.

---

## Tests (3 files)

1. `tests/test_vis3a_layout_strip_navigation.py` — strip absent, equal CSS, nav controls  
2. `tests/test_vis3a_tf_context_and_trades.py` — historical context + isolation  
3. `tests/test_vis2b_layout_dom.py` — updated for strip removal / v2 hook  

Result: **32 passed** (including prior VIS2B candle/identity suites).

---

## Candidate verification screenshots

Under `…/vis3a_functional_chart_workspace/screenshots/` (not for git):

`grid_equal_1440.png`, `grid_equal_1920.png`, `M15/M30/H1/H4_context_and_trades.png`, `trade_selected.png`, `historical_pan.png`, `sl_tp_offscreen_cue.png`

Candidate payload only:

```text
data/candidate/architecture_recovery/vis3a_functional_chart_workspace/timeframe_chart_truth.json
```

Live public `timeframe_chart_truth.json` **not** rewritten by this stage.

---

## Compliance

| Gate | Value |
|---|---|
| production files | 3 |
| test files | 3 |
| trading/manager/OPS/book/risk changes | 0 |
| process restarts | 0 |
| live public writes | 0 |
| local commit | 1 (this stage) |
| pushes | 0 |

---

## Acceptance

| Gate | Met |
|---|---|
| four equal panels | true |
| global lifecycle strip present | false |
| horizontal pan / time zoom / reset/fit/latest | true |
| viewport survives refresh | true |
| historical TF context per chart | true |
| cross-TF context / trade contamination | 0 |
| entry/exit/open distinguishable + selection | true |
| SL/TP off-screen awareness | true |
| 1440 clipping | false |
| OPS relocation falsely claimed complete | false |
| tests green | true |

---

**Final status:** `VIS3A_FUNCTIONAL_CHART_WORKSPACE_CANDIDATE_READY`
