# Live Context Refresh Once

**Mode:** manual once  
**Script:** `scripts/live/run_live_context_refresh_once.py`  
**Status:** `data/live/live_context_refresh_status.json`  
**Log:** `logs/live_context_refresh.log`

Shadow-only technical refresh. Does **not** enable execution.

---

## Purpose

After the decision logger was introduced, cognition/lifecycle artifacts can lag the live feed by one or more 15m candles.

This once-mode command catches up:

1. Compare `live_market_feed` latest timestamp vs `market_context_lifecycle_memory` latest timestamp
2. If lifecycle lags → run `build_market_context_shadow_chain.py`
3. Always run `append_context_decision_log.py`
4. Persist status + append-only log lines

---

## What it does / does not do

Does:
- rebuild shadow cognition chain when stale
- append one decision-log snapshot
- write status JSON and log file

Does **not**:
- change model / auction / cognitive / final / lifecycle source logic
- mutate live feed
- modify runtime-stack behavior
- start dashboard
- start visual server
- enable execution
- create orders / paper orders

---

## Run

```bash
cd /Users/fontecrypto/btc-ml
venv/bin/python scripts/live/run_live_context_refresh_once.py
```

Or:

```bash
make live-context-refresh-once
```

Options:

- `--force-rebuild` — always rebuild shadow chain
- `--skip-rebuild` — never rebuild; decision logger only

---

## Status fields

Key fields in `live_context_refresh_status.json`:

- `status` (`OK` / `ERROR`)
- `live_feed_latest_timestamp`
- `lifecycle_latest_timestamp`
- `live_to_lifecycle_lag_seconds`
- `shadow_chain_rebuild_ran`
- `decision_logger_ok`
- `execution_enabled=false`
- `orders_created=false`
- `paper_orders_created=false`

---

## Relation to decision logger

This orchestrator is the manual catch-up path.

The decision logger remains the append-only evidence store.

Next audits still required before any execution claim:

1. decision latency audit
2. no-repaint audit
3. paper execution simulator
