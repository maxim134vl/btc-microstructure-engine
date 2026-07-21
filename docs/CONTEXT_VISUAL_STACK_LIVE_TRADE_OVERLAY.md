# Context Visual Stack — Live Trade Overlay

## Purpose

Stable live viewer for:

- live candles
- market context / lifecycle
- paper signals / orders / entries / exits
- open positions with stop-loss / take-profit
- realized / unrealized PnL
- bounded paper controller cycles / actions

Three layers:

1. **Viewer** — no-cache static server on `127.0.0.1:8765`
2. **Visual refresher** — background process, 15–30s, writes visual JSON only
3. **Paper controller** — separate process; visual layer only reads its outputs

## Commands

```bash
make context-visual-stack-restart
make context-visual-stack-status
make context-visual-stack-tail
```

Open: http://127.0.0.1:8765/?v=live-context-paper-trades

## macOS-safe launcher

`scripts/context_visual_stack_ctl.sh` uses **nohup + `$!` pid files**.

- **No `setsid`** (absent on many macOS installs).
- Writes `runtime_context_viewer.pid` / `runtime_context_visual_refresher.pid`.
- Duplicate `start` is blocked if managed viewer/refresher is already alive (use `restart`).
- Foreign process on `:8765` is **not** killed; ctl errors instead.
- Viewer logs once under nohup redirect (no double `viewer_start` lines).
- `status` prints `viewer_alive`, `refresher_alive`, `port_8765_listening`, `visual_status`, `visual_refresh_age_seconds`.
- `tail` collapses adjacent duplicate log lines.

## Allowed writes

- `apps/context_visualizer/public/data/context_visual.json`
- `.../paper_trade_overlays.json`
- `.../open_positions.json`
- `.../closed_trades.json`
- `.../controller_cycles.json`
- `.../visual_status.json`
- plus lifecycle_* visual JSON from generator
- `logs/context_visual_refresher.log`
- `logs/context_viewer_8765.log`
- `runtime_context_visual_refresher.pid` / `.lock`
- `runtime_context_viewer.pid`
- `data/research/visual_context_stack_*.json`

## Forbidden

- paper ledger writes
- decision log writes
- live refresh / shadow-chain rebuild
- controller stop/restart
- execution / exchange API / dashboard / model fit

## Freshness semantics

- `source_lag_minutes` — age of live/decision source
- `visual_refresh_age_seconds` — age of last successful visual JSON write
- `SOURCE WAITING / NO NEW BAR` when refresher is alive/fresh but source lag is high
- `VISUAL DATA STALE` only when the visual refresher itself is stale

## Safety

- Synthetic research prices near `100000` are excluded from overlays
- Real paper prices (e.g. 65913 / 66240.02) are preserved
- Duplicate refresher starts are blocked by lock file
