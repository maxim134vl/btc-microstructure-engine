# Market Context Visual Auto-Refresh

Shadow-only auto-refresh for the Lifecycle Context Viewer.

This layer **does not** integrate market context into the canonical pipeline,
does **not** enable execution, and does **not** change auction / lifecycle rules,
model logic, retrain, governance, or benchmark producers.

## What it does

`scripts/research/run_market_context_visual_refresher.py` periodically runs the
existing builder:

```bash
venv/bin/python scripts/research/build_market_context_shadow_chain.py
```

That rebuilds shadow cognition parquet + sandbox visual JSON under:

```text
apps/context_visualizer/public/data/
  lifecycle_candles.json
  lifecycle_context_episodes.json
  lifecycle_latest.json
```

The viewer polls `lifecycle_latest.json` every 60s with `cache: "no-store"` and
`?v=<Date.now()>`. When the timestamp changes, it reloads candles + episodes and
redraws without a manual page refresh.

## Cadence

| Layer | Interval |
|---|---|
| Refresher loop | 180 seconds (default) |
| Viewer poll | 60 seconds |
| Stale threshold | 30 minutes (`live − visual` lag) |

`make runtime-stack` starts:

1. an immediate `--once` refresh
2. a background loop refresher
3. a static viewer on `http://127.0.0.1:8765/`

Old refresher processes are **stopped and restarted** (never silently adopted).

## Commands

One-shot:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/run_market_context_visual_refresher.py --once
```

Loop:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/run_market_context_visual_refresher.py --interval-seconds 180
```

Stack:

```bash
make runtime-stack
make runtime-stack-status
make runtime-stack-stop
```

## Status / files

| File | Role |
|---|---|
| `logs/market_context_visual_refresher.log` | structured run log |
| `runtime_context_visual_refresher.pid` | process pid |
| `runtime_context_visual_refresher.lock` | overlap lock |
| `data/cognition/market_context_visual_refresher_status.json` | status JSON |

Status fields include `latest_live_timestamp`, `latest_visual_timestamp`,
`live_to_visual_lag_minutes`, `visual_data_stale`, run counters, and
`shadow_only: true`.

`visual_data_stale` is true when live lag is **greater than** 30 minutes
(boundary-safe: exactly 30 minutes is not stale).

## Viewer badges

- Fresh: `LIVE SNAPSHOT / AUTO-REFRESH`
- Stale: `VISUAL DATA STALE`
- Always shows: `Last visual refresh: … · Live lag: … min`

If you see **VISUAL DATA STALE**:

1. confirm feed/runtime are up (`make runtime-stack-status`)
2. check refresher is RUNNING
3. inspect `logs/market_context_visual_refresher.log`
4. run a one-shot refresh
5. hard-reload only if the viewer process itself is old (cache-bust should already avoid JSON cache traps)

## Why generated files are not committed

Shadow parquet + visual JSON are derived from live/runtime data and refresh
continuously. They are gitignored (including
`apps/context_visualizer/public/data/` and the refresher status /
pid / lock / logs). Source scripts and docs remain tracked.

## Explicit non-goals

- no CANONICAL_PIPELINE change
- no execution enablement
- no auction_context_arbitration / lifecycle rule edits
- no model / retrain / benchmark / conformance / governance changes
