# VIS — Trade Render + TF Context History Fix

**Status:** `VIS_TRADE_RENDER_CONTEXT_FIX_CANDIDATE_READY`

**Branch:** `memory/canonical-system`  
**Mode:** `paper_only = true`, real execution disabled  
**URLs:** `/index.html?tf=M15|M30|H1|H4`

---

## Defects proven (before fix)

| Defect | Evidence |
| --- | --- |
| Technical ID on chart | Live public v2 `display_label = "M15 · e3ee3129"`; frontend `publicNumber` fell back to it |
| No TradingView position | Overlay drew markers + edge `SL`/`TP` captions only; no Entry line/price, no green/red zones |
| Context visually absent | `context_segments` present (M15:14) but band alpha ~0.08–0.14; price scale ignored SL/TP |

Root cause detail: `data/candidate/architecture_recovery/vis_trade_render_context_fix/baseline_marker_identity.json`

---

## Fixes

### 1. Stable `TF_N` on canvas

- Adapter (v3): `assign_tf_ordinals` → `public_number` / `display_label` = `M15_1`, …
- Frontend: `isStableTfNumber` + `ensureTfOrdinals` — rejects hex/` · ` labels; backfills ordinals if live v2 still loads
- Full `trade_id` / `position_id` only in tooltip/details

### 2. TradingView-like Long/Short position

- Green reward zone Entry↔Take (when take ≠ null)
- Red risk zone Entry↔Stop (when stop ≠ null)
- Entry horizontal line + `M15_1  Entry  64,136.00`
- Closed: zones entry→exit; exit `× M15_1  Exit  …`
- Open: zones entry→latest candle; `· OPEN`; no exit
- Price scale expanded to include Entry/SL/TP

### 3. Historical TF context

- Source unchanged: `timeframe_command_memory`
- Stronger translucent bands + 3px accent rail behind candles
- TF-isolated; pan/zoom aligned

---

## Production files (3)

1. `apps/context_visualizer/timeframe_chart_truth.py` — candidate dir `vis_trade_render_context_fix`
2. `apps/context_visualizer/public/lifecycle_app.js` — ordinals, zones, context visibility
3. `apps/context_visualizer/public/index.html` — cache-bust script version

## Tests (3)

- `tests/test_vis3a_layout_strip_navigation.py`
- `tests/test_vis3a_tf_context_and_trades.py`
- `tests/test_vis2b_layout_dom.py`

**13 passed.**

---

## Compliance

```text
production files changed = 3
test files changed = 3
trading/manager/book/OPS/risk changes = 0
process restarts = 0
live public writes = 0
pushes = 0
```

Live `public/data/timeframe_chart_truth.json` remains **v2** (not rewritten). Frontend backfill makes `TF_N` visible even on v2.

---

## Candidate

`data/candidate/architecture_recovery/vis_trade_render_context_fix/`

Evidence + screenshots (screenshots not for Git).

---

## Final status

```text
VIS_TRADE_RENDER_CONTEXT_FIX_CANDIDATE_READY
```
