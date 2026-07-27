# VIS3C — Standalone TF Charts Candidate

**Status:** `VIS3C_STANDALONE_TF_CHARTS_CANDIDATE_READY`

**Branch:** `memory/canonical-system`  
**Mode:** `paper_only = true`, real execution disabled  
**Baseline production commit:** `5d490fa` (VIS3A) / activation docs `be7ea0e` (VIS3B)

---

## Scope delivered

1. Four standalone URLs: `/index.html?tf=M15|M30|H1|H4`
2. TradingView-like order markers with stable public numbers `TF_N`
3. Historical per-TF context bands from `timeframe_command_memory`
4. Strict TF isolation of contexts and trades (payload + DOM)

No OPS / PnL / risk / manager / trader / book / pipeline changes.  
Candidate-only: no process restarts, no live public JSON writes.

---

## Root-cause diagnosis (contamination)

| Level | Finding |
| --- | --- |
| Adapter payload | Foreign entities = **0** per TF |
| Public JSON (live) | Already TF-isolated under VIS3A v2; not rewritten in VIS3C |
| Frontend collection | Previously mounted **all four** panels |
| Chart render loop | CSS `display:none` hid non-selected panels — **DOM still contained foreign charts** |

**Verdict:** Re-contamination was **UI architecture** (hidden GRID), not book copying. Fix mounts **one** panel for `?tf=`.

Evidence: `data/candidate/architecture_recovery/vis3c_standalone_tf_charts/baseline_contamination.json`

| | M15 | M30 | H1 | H4 |
| --- | ---: | ---: | ---: | ---: |
| Closed trades | 6 | 5 | 3 | 0 |
| Open positions | 1 | 1 | 1 | 1 |
| Foreign entities | 0 | 0 | 0 | 0 |

---

## Production changes (3)

1. `apps/context_visualizer/timeframe_chart_truth.py` — schema `timeframe_chart_truth_v3`; `assign_tf_ordinals()`; `context_history` alias; `trade_numbering`; candidate dir `vis3c_standalone_tf_charts`; `standalone_tf_urls` contract
2. `apps/context_visualizer/public/index.html` — TF nav links; empty `#tfChartHost` (no static four-panel GRID)
3. `apps/context_visualizer/public/lifecycle_app.js` — parse `?tf=`; mount one panel; TradingView markers `▲/▼/× TF_N`; selection pairing; viewport controls preserved; `__VIS3C__` hooks

---

## Tests (3)

1. `tests/test_vis3a_layout_strip_navigation.py` — standalone URL / nav / no GRID
2. `tests/test_vis3a_tf_context_and_trades.py` — v3 context history + isolation + ordinals
3. `tests/test_vis2b_layout_dom.py` — marker contract + generator hook (v3)

**Result:** 19 passed.

---

## Standalone URL contract

| URL | DOM |
| --- | --- |
| `?tf=M15` | only M15 `.tf-chart-panel` |
| `?tf=M30` | only M30 |
| `?tf=H1` | only H1 |
| `?tf=H4` | only H4 |

Default when `tf` missing: **M15**.  
Header links navigate to independent URLs (not CSS hide).

---

## Historical context

Source: `data/trading/manager/timeframe_command_memory.parquet` via `CommandBus` / `build_tf_context_segments`.

| TF | Segments (candidate window) |
| --- | ---: |
| M15 | 14 |
| M30 | 16 |
| H1 | 10 |
| H4 | 2 |

Rendered as per-chart background bands (scroll/zoom with candles).  
Global lifecycle strip: **absent**.

---

## Trade numbering

Deterministic per TF: `entry_timestamp` → `created_at` → `trade_id`/`position_id`.

Examples: `M15_1` … `M15_7`, `M30_1` …, `H1_1` …, `H4_1`.  
Long IDs only in tooltip/detail panel.

Markers:

- LONG entry: `▲ TF_N` below candle
- SHORT entry: `▼ TF_N` above candle
- Exit: `× TF_N`
- Open: entry + OPEN + entry/SL/TP lines; no exit

---

## Candidate artifacts

Directory: `data/candidate/architecture_recovery/vis3c_standalone_tf_charts/`

- `timeframe_chart_truth.json` (+ per-TF slices)
- `baseline_contamination.json`
- `payload_tf_isolation.json`
- `context_tf_isolation.json`
- `trade_tf_isolation.json`
- `standalone_url_contract.json`
- `trade_number_mapping.json`
- `trade_marker_contract.json`
- `viewport_regression.json`
- `test_results.json`
- Screenshots (not for Git): `M15_standalone.png`, `M30_standalone.png`, `H1_standalone.png`, `H4_standalone.png`, `M15_trade_M15_1.png`, `M30_trade_M30_1.png`, `*_context_history.png`

---

## Compliance

```text
production files changed = 3
test files changed = 3
OPS / trading / manager / book / risk/PnL changes = 0
process restarts = 0
live public writes = 0
trading writes = 0
pushes = 0
```

Live `apps/context_visualizer/public/data/timeframe_chart_truth.json` remains **v2** (activation of v3 deferred).

---

## Acceptance gates

```text
four standalone URLs = true
one chart per URL = true
historical M15/M30/H1/H4 context restored = true
cross-TF context count = 0
foreign trades per TF = 0
TradingView-style markers = true
public ordinals TF_N = true
long IDs on canvas = false
entry/exit same ordinal = true
ordinal stable / viewport-independent = true
global lifecycle strip = absent
tests green = true
```

---

## Final status

```text
VIS3C_STANDALONE_TF_CHARTS_CANDIDATE_READY
```
