# Context Decision Logger

**Status:** shadow-only, append-only, execution disabled  
**Artifact:** `data/live/context_decision_log.parquet`  
**Script:** `scripts/live/append_context_decision_log.py`

> This logger records shadow-only market context decisions. It does not enable execution and must not be used to place orders.

---

## 1. Purpose

After the Market Context Stage Review Audit, execution readiness remains **BLOCKED** primarily because there is no append-only live decision evidence.

This logger creates that evidence: for each new closed candle that has lifecycle context, it records a snapshot of what the cognition/context stack knew at write time.

It exists so later audits can prove:

- what decision was available at time T
- whether later rebuilds repainted that decision
- how late the decision was vs the live candle

---

## 2. Why it is required before execution

Execution / paper simulation must not begin until:

1. append-only context decision log exists
2. decision latency audit exists
3. no-repaint audit exists
4. paper execution simulator exists
5. setup/risk gate exists

Without (1), there is no immutable transcript of live decisions. Visual JSON and rebuildable parquet memories are **not** a live decision proof.

---

## 3. Append-only guarantees

| Rule | Behavior |
|------|----------|
| Existing rows preserved | Previous decision rows are never rewritten |
| Newer candle only | Append only when `candle_timestamp` is newer than the latest logged candle |
| Same candle + same hash | Exit cleanly as `SKIPPED_DUPLICATE` |
| Same candle + different hash | Fail safely as `MUTATION_CONFLICT` (no overwrite) |
| Stale lifecycle | Still append, but mark `decision_stale=True` / `technical_refresh_lag_present=True` |
| Safety fields | Always force `action_allowed=False`, `shadow_only=True`, `execution_enabled=False` |

Atomic write uses temp file + `os.replace`. Content of prior rows is never altered.

---

## 4. Schema

Identity / time:

- `decision_id`, `decision_written_at_utc`
- `candle_timestamp`, `candle_close_time_utc`
- `source_timeframe` (`15m`)
- `runtime_pid`, `pipeline_cycle`, `runtime_segments`, `total_runtime_log_cycles`

Source freshness + lag:

- `*_latest_timestamp` for live / auction / cognitive / final / lifecycle
- `live_to_*_lag_seconds`
- `decision_lag_vs_live_seconds`, `decision_lag_vs_lifecycle_seconds`

Context fields:

- auction / cognitive / raw / active / lifecycle fields
- `active_context_age_bars`, `active_context_started_at`, `invalidation_type`

Safety:

- `action_allowed=False`
- `shadow_only=True`
- `execution_enabled=False`
- `visual_json_used_for_execution=False`
- `orders_created=False`
- `paper_orders_created=False`
- `technical_refresh_lag_present`, `decision_stale`, `execution_readiness_blocked=True`

Integrity:

- `source_files_hash`, `decision_payload_hash`
- `schema_version`, `logger_version`

---

## 5. Safety restrictions

- Does **not** change model / auction / cognitive / final / lifecycle logic
- Does **not** place orders or enable paper/real execution
- Does **not** read visual JSON as decision source
- Does **not** fabricate context for live candles missing lifecycle rows
- Forces all execution-related flags to disabled / false

---

## 6. How to run once manually

```bash
cd /Users/fontecrypto/btc-ml
venv/bin/python scripts/live/append_context_decision_log.py
```

Or via Makefile:

```bash
make context-decision-log-once
```

Optional custom path (tests / scratch):

```bash
venv/bin/python scripts/live/append_context_decision_log.py \
  --log-path /tmp/context_decision_log.parquet
```

---

## 7. What counts as a stale decision

A decision is stale when:

`lifecycle_latest_timestamp < live_feed_latest_timestamp`

In that case the logger:

- uses the **lifecycle latest** candle as the decision candle
- does **not** invent context for newer live-only candles
- sets `decision_stale=True`
- sets `technical_refresh_lag_present=True`
- keeps `execution_readiness_blocked=True`

Stale decisions are still useful evidence of technical refresh lag.

---

## 8. Why visual JSON is not a source

Visual JSON (`lifecycle_latest.json`, candles, episodes) is a display layer.

It may lag, be rebuilt, or be cache-busted independently of cognition artifacts.

Therefore:

- decision logger never depends on visual JSON
- visual JSON must never be used for execution
- cognition/lifecycle parquet artifacts are the only context sources for this logger

---

## 9. Why execution remains disabled

Even with this logger present:

- no decision latency audit yet
- no no-repaint audit yet
- no paper execution simulator yet
- no setup/risk gate yet

`execution_enabled` is always forced `False`.  
`execution_readiness_blocked` is always `True` in this phase.

---

## 10. Next audits

1. **Decision latency audit** — measure write lag vs candle close / live feed using this log  
2. **No-repaint audit** — compare later rebuilds against logged `decision_payload_hash`  
3. **Paper execution simulator** — consume decision log only after latency + no-repaint pass  

Primary stage-review recommendation remains: keep observing current lifecycle parameters; do not enable execution yet.
