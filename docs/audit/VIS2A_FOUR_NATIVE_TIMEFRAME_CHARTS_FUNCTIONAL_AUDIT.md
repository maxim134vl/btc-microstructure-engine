# VIS2A — Four Native Timeframe Charts Functional Audit

**Status:** `VIS2A_FOUR_NATIVE_TIMEFRAME_CHARTS_ARCHITECTURE_PROVEN`  
**Branch:** `memory/canonical-system` @ `718fec6`  
**Mode:** `paper_only=true`, `execution_enabled=false`  
**Scope:** read-only architecture audit (no production/test changes, no process restarts, no commits)

Evidence: `data/candidate/architecture_recovery/vis2a_four_native_timeframe_charts_audit/`

---

## A. Result

All acceptance gates pass. M15 candles are native from the live Binance feed. M30/H1/H4 have **no separate live OHLCV parquet for the visualizer**; their canonical chart source is **aggregate-from-M15** via the already-active trading contract `multi_timeframe_availability.build_completed_bars` (proven OHLC-identical base vs `candle_structure_memory`). Current visualizer contamination is a single M15 canvas + `ALL` overlay union + global bands + fragile `CTX` suffix labels.

PIDs re-verified alive: pipeline `4618`, OPS `71811`, Vite `66359`, manager `61283`, traders `61284–61287`, refresher `84045`.

---

## B. Current Visualizer Stack

```text
live_market_feed.parquet (M15 closed)
  + lifecycle memory/episodes
  + timeframe_traders/{TF} books
→ generate_lifecycle_context_data.py + trading_truth.py
→ run_market_context_visual_refresher.py
→ apps/context_visualizer/public/data/*.json
→ lifecycle_app.js (index.html)
→ single #lifecycleCanvas
```

| Layer | Path | Role |
| --- | --- | --- |
| Candle source | `data/live/live_market_feed.parquet` | M15 only |
| TF aggregation (canonical) | `multi_timeframe_availability.py::build_completed_bars` | Not wired to visualizer |
| TF aggregation (legacy unused) | `legacy_app.js::aggregateRows` | Not loaded by `index.html` |
| Context / lifecycle | `market_context_lifecycle_{memory,episodes}.parquet` | Global |
| Trades / positions | `data/trading/timeframe_traders/{TF}/` | Per TF |
| Refresher | `scripts/live/run_market_context_visual_refresher.py` | Public JSON writer |
| Frontend | `public/lifecycle_app.js` | One chart |

---

## C. Candle Sources

| TF | Source path | Producer | Native/Aggregated | Live | Visualizer wired |
| --- | --- | --- | --- | ---: | ---: |
| M15 | `data/live/live_market_feed.parquet` | `live_binance_feed_v2.py` (`15m`, closed only) | **NATIVE** | yes | yes |
| M30 | Aggregate M15 → `30min` | `build_completed_bars` | **AGGREGATED** | yes | **no** |
| H1 | Aggregate M15 → `1h` | `build_completed_bars` | **AGGREGATED** | yes | **no** |
| H4 | Aggregate M15 → `4h` | `build_completed_bars` | **AGGREGATED** | yes | **no** |

Parity proof (bounded join): `live_market_feed` ∩ `candle_structure_memory` = 3800 rows, max OHLC abs diff = **0** on all four fields; shared tip `2026-07-27T12:30:00Z`.

Completed-bar counts from the same feed window via `build_completed_bars`: M15 3800, M30 1926, H1 972, H4 246.

---

## D. Candle Aggregation

Contract (runtime, not a new design):

- Timezone: **UTC**
- Label: **BAR_OPEN**
- Close: `bar_open + duration` (900 / 1800 / 3600 / 14400)
- OHLC: `open=first`, `high=max`, `low=min`, `close=last`, `volume=sum`
- Partial bars: **excluded** (`bar_close <= evaluation_timestamp`; contract `forbid_unclosed_bar=true`)
- Boundaries: M30 on `:00/:30`; H1 on hour; H4 on pandas `4h` UTC buckets (`00/04/08/12/16/20`)

---

## E. Timestamp Semantics

| Entity | Field | Meaning |
| --- | --- | --- |
| Candle | `timestamp` / `bar_open` | BAR_OPEN |
| Candle close | `bar_close` | open + duration |
| Fill / trade entry | `fill_timestamp` / `entry_ts` | Event time; source `live_market_feed_completed_bar_close` |
| TF state | `source_bar_open` / `source_bar_close` / `evaluation_timestamp` | Completed-bar join |
| Lifecycle | memory `timestamp` | Global M15-bar time |

**Marker gate:** place on the TF interval that contains the event; keep the real event timestamp (do not rewrite identity to bar_open).

---

## F. Partial-Bar Policy

- Live feed persists **closed M15 only** (`kline["x"]` / catch-up closed).
- Trading decisions / fills use **completed bar close**.
- Visualizer charts must show **confirmed bars only** for all four TFs; any future forming candle must be explicitly marked unconfirmed (not required for VIS2B minimum).

---

## G. Timeframe State Sources

Per TF:

1. **Availability:** `data/runtime/multi_timeframe_availability_latest.json`
2. **Directional / episode:** `timeframe_state_adapter` → stamped on manager commands in `timeframe_manager_latest.json`
3. **Position machine:** `data/trading/timeframe_traders/{TF}/controller_state.json`

Do not mix availability (`FRESH_EVENT` / `AVAILABLE_LAST_CONFIRMED`) with directional state (`LONG_CONTEXT` / `SHORT_CONTEXT` / `OBSERVE`).

Tip at audit: all four manager commands `HOLD` on `*:887`; availability M15 `FRESH_EVENT`, M30/H1/H4 `AVAILABLE_LAST_CONFIRMED`.

---

## H. Global Lifecycle Source

Preferred strip source: **collapsed** `market_context_lifecycle_episodes.parquet`.  
Active tip / live continuity: `market_context_lifecycle_memory.parquet` (`context_episode_id`).

Active tip at audit: episode **887**, `LONG_CONTEXT`, `ACTIVE`.

---

## I. Global vs TF Context

| Field | Global | TF-specific |
| --- | ---: | ---: |
| lifecycle episode | yes | namespaced `TF:id` on commands/trades |
| market context / bias | yes | interpreted per TF |
| TF availability | no | yes |
| position side / open | no | yes |
| manager command | no | yes |

---

## J. Trade and Position Sources

Canonical only: `data/trading/timeframe_traders/{M15,M30,H1,H4}/`  
Entities: signals, orders, fills, positions, trades.  
Exclude research / legacy / dashboard-derived / quarantine.

| TF | Closed | Open | SL/TP |
| --- | ---: | ---: | --- |
| M15 | 4 | 1 | trades columns; positions via `metadata_json` |
| M30 | 3 | 1 | same |
| H1 | 2 | 1 | same |
| H4 | 0 | 1 | positions meta (no `trades.parquet`) |

Missing SL/TP → `null`, never `0`. Frontend must not invent stops.

---

## K. Trade Identity

Primary: `trade_id` / `position_id` with display like `M15-T01`.  
Secondary: global episode annotation only when it matches real `context_episode_id`.  
**Forbidden:** treating `CTX N` as the trade id.

`lifecycle_app.js::contextNumber` (`/(\d+)$/`) is the fragile suffix parser to replace with fallback to full `episode_key` / `TF:id`.

---

## L. Episode 743

Three closed TF entities share `lifecycle_episode_id` `*:743` and the same `manager_cycle_id` `TF_MGR_CYCLE_c1a322ad7fd465a4` (entry/exit `2026-07-26T14:30Z`→`15:30Z`).

**Target:** one marker per own chart; global strip **once**.

**Identity proof:** global `episode_id=743` in episodes parquet is **2026-07-08** (different window). Memory at the trade window is `context_episode_id=879`. Therefore suffix `:743` ≠ global CTX 743; regex “CTX 743” would mis-bind.

---

## M. CTX 879 / 881

| Episode | Global window | TF closed | TF open |
| --- | --- | --- | --- |
| 879 | 2026-07-24 → 2026-07-26 | M15 + M30 (`*:879`) | H1 open (`H1:879`) with SL/TP |
| 881 | single-bar 2026-07-26 23:00 in memory | none | H4 open (`H4:881`) with SL/TP |

Partial CTX labels today: only overlays that successfully parse trailing digits get a label; missing/non-matching keys stay unlabeled.

Target: episode label independent of trade id; fallback to stable key string.

---

## N. Current Contamination Root Cause

```text
M15 candles
+ matchesTimeframe(ALL) → all TF trades/positions
+ global lifecycle bands (no TF)
+ CTX labels from episode suffix
→ one mixed M15 plane
```

---

## O. TF Isolation Contract

| Overlay | M15 | M30 | H1 | H4 |
| --- | ---: | ---: | ---: | ---: |
| Native/canonical candles | yes | yes | yes | yes |
| Own open positions | yes | yes | yes | yes |
| Own closed trades | yes | yes | yes | yes |
| Own TF state | yes | yes | yes | yes |
| Global lifecycle | strip only | strip only | strip only | strip only |

---

## P. Global Strip Contract

One strip above the grid: episode id/key, state, start/end, active flag, global LONG/SHORT/OBSERVE.  
Not duplicated per chart. Not a trade overlay. Prefer collapsed episode bands.

---

## Q. Four-Chart Layout

Desktop 2×2 under the strip; narrow = 1 column; expand = full-width TF.  
Selector target: `GRID | M15 | M30 | H1 | H4` (replace contaminated `ALL`).  
Phase-1 zoom/crosshair: **independent** (sync deferred).  
Header PnL from canonical performance truth (OPS path), not chart math.

---

## R. Detailed PnL / Metrics Removal

| Panel | HTML | JS | Data |
| --- | --- | --- | --- |
| Detailed PnL | `#paperPnlBlock` | `renderPnlPanel` | `pnl_summary.json` |
| Trading Model Evaluation Metrics | `#modelMetricsBlock` | `renderModelMetricsPanel` | same / metrics fields |

After OPS performance activation: **remove from visualizer layout**; keep backend performance adapter for OPS. Freed space → taller 2×2 charts only.

---

## S. Payload Design

Candidate (not created live in VIS2A): `timeframe_chart_truth.json`

```text
schema_version, generated_at
global_lifecycle: { active_episode, episodes }
timeframes: { M15|M30|H1|H4 → candles, state, open_positions, closed_trades, performance_summary, freshness }
data_quality: { missing, stale, excluded, duplicates }
```

Migration: keep old `lifecycle_candles.json` until parity; frontend candidate reads new payload; then drop mixed overlays.

---

## T. History Windows

Prefer **same calendar range** across TFs (equal bar counts ≠ equal time).  
Default suggestion: last 7 calendar days (cap M15 then aggregate HTF inside the window). Do not ship full parquet to the browser.

---

## U. Freshness

Per TF: `latest_confirmed_close`, `source_tip`, `freshness_seconds`, status ∈  
`FRESH | AVAILABLE_LAST_CONFIRMED | STALE | NOT_LIVE | SOURCE_UNAVAILABLE`.

H4 between closes with last confirmed bar → **not** STALE solely due to cadence.

---

## V. Future Production Scope (VIS2B)

≤ 4 production files:

1. Multi-TF chart truth adapter (new `timeframe_chart_truth.py` or controlled extension of `trading_truth.py`)
2. Generator/refresher write hook (`generate_lifecycle_context_data.py` and/or refresher — one write site preferred)
3. `lifecycle_app.js` multi-chart renderer + isolation
4. `index.html` (+ CSS): 2×2 layout, strip, remove PnL/metrics blocks

Import-only reuse of `build_completed_bars` and performance truth. **No** manager/trader/core edits → scope stays within limit.

---

## W. VIS2B Test Plan

Candle isolation · trade isolation · episode-743 triple · CTX≠trade_id + fallback · exclude research/legacy/quarantine · PnL/metrics absent · OPS performance/risk unchanged.

---

## X. Compliance

| Constraint | Value |
| --- | --- |
| production source changes | 0 |
| test changes | 0 |
| process start/stop/restart | 0 |
| live/public JSON schema writes | 0 |
| trading writes / backfills | 0 |
| commits / pushes | 0 |

Candidate evidence + this audit doc only.

---

## Direct answers

1. **M15 candles:** `data/live/live_market_feed.parquet` (native closed 15m).  
2. **M30 candles:** aggregate from that M15 feed via `build_completed_bars(..., "M30")`.  
3. **H1 candles:** same aggregate `"H1"`.  
4. **H4 candles:** same aggregate `"H4"`.  
5. **Per chart state:** own TF availability + directional TF state + own positions/trades; not foreign TF overlays.  
6. **Global strip once:** episode id/key, state, start/end, active, global LONG/SHORT/OBSERVE.  
7. **Trades per chart:** only that TF’s book entities under `timeframe_traders/{TF}/`.  
8. **CTX vs trade id:** primary = `trade_id` / `M15-Tn`; CTX secondary only when it is the real global `context_episode_id`; never use CTX as trade number.  
9. **Remove panels:** Detailed PnL + Trading Model Evaluation Metrics from visualizer.  
10. **VIS2B files:** chart-truth adapter · generator/refresher hook · `lifecycle_app.js` · `index.html`(+CSS).

---

**Final status:** `VIS2A_FOUR_NATIVE_TIMEFRAME_CHARTS_ARCHITECTURE_PROVEN`
