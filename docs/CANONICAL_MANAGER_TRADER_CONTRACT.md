# Canonical Manager / Timeframe Trader Contract

Status: production, activated at `2026-07-24T20:20:14.398043Z`
Schema: `timeframe_manager_command_v1`
Mode: paper only, `execution_enabled = false`, `exchange_enabled = false`

This document is the canonical contract for the S4.1 runtime: one deterministic
manager, four independent timeframe traders, one shared paper execution core.
It defines ownership, schemas, timestamps and invariants. Anything not listed
here as writable by the manager or a trader is read-only for them.

---

## 1. Component boundaries

| Component | Module | Writes | Reads |
| --- | --- | --- | --- |
| Timeframe state adapter | `src/btc_ml/trading/timeframe_state_adapter.py` | nothing | MTF availability runtime, lifecycle/context memory |
| Manager | `src/btc_ml/trading/timeframe_manager.py` | command bus, manager state, latest snapshot, portfolio summary | state adapter output, trader books (read-only), risk config |
| Trader (one per timeframe) | `src/btc_ml/trading/timeframe_trader.py` | own book only | own timeframe slice of the command bus, market data |
| Shared execution core | `src/btc_ml/trading/paper_trader_engine.py` + `paper_core.py` | via the owning trader | market data |
| Portfolio risk coordinator | `src/btc_ml/trading/portfolio_risk.py` | nothing | trader books, risk config |

Forbidden for every component above: writing cognition, context, decision,
Stage-1/Stage-2 datasets, or any other trader's book; calling an exchange;
placing real orders.

## 2. Timeframe scope

Live traders: `M15`, `M30`, `H1`, `H4`.

`D1` is not a trader. The adapter reports it as
`TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER`; the manager never emits a D1
command and no D1 book exists.

## 3. Timeframe state adapter contract

Per timeframe, the adapter returns exactly one point-in-time state resolved from
that timeframe's own source. Hard rule: `source_bar_close <= evaluation_timestamp`.

Operational (actionable) availability statuses:

```text
FRESH_EVENT
AVAILABLE_LAST_CONFIRMED
NO_EVENT_STATE_UNCHANGED
```

Non-actionable statuses map to `NO_ACTION` with the status as reason code:

```text
WAITING_FOR_BAR_CLOSE
UPSTREAM_STALE
WRITER_STALE
DATASET_MISSING
SCHEMA_INVALID
TIMEFRAME_NOT_LIVE
```

Never allowed: reading another timeframe's state, substituting a global
direction, using an unclosed bar, using a future state, reading a research path,
or synthesising a direction.

## 4. Command contract

Deterministic key (SHA-256 over the tuple, prefix `TF_CMD_`):

```text
asset + timeframe + evaluation_timestamp + lifecycle_episode_id + intent
```

Commands are immutable. A repeated manager cycle over the same evaluation
produces the identical `command_id` and is rejected by the bus as a duplicate.

Valid intents:

```text
OPEN_LONG  OPEN_SHORT  HOLD  CLOSE  NO_ACTION
```

Columns (`src/btc_ml/trading/command_bus.py::COMMAND_COLUMNS`):

```text
command_id, manager_cycle_id, schema_version,
asset, timeframe,
evaluation_timestamp, source_bar_open, source_bar_close,
source_state_timestamp, source_event_timestamp,
timeframe_state, timeframe_direction, availability_status,
lifecycle_episode_id, lifecycle_phase,
intent, action_allowed, reason_codes, exit_reason,
confidence, alignment_score, persistence_score, structural_rank, location_bias,
requested_risk_usd, approved_risk_usd, portfolio_open_risk_usd,
stop_reference, invalidation_reference, command_ttl_seconds,
cross_timeframe_metadata,
created_at, source_lineage, paper_only, execution_enabled
```

`cross_timeframe_metadata` is descriptive only. In S4.1 it must never act as a
directional veto: an H1 SHORT never suppresses an M15 LONG.

## 5. Command bus

```text
data/trading/manager/timeframe_command_memory.parquet   append-only history
data/trading/manager/timeframe_command_memory.parquet.meta.json
data/trading/manager/manager_state.json                 per-timeframe manager memory
data/trading/manager/portfolio_summary.json             derived portfolio read-model
data/runtime/timeframe_manager_latest.json              latest cycle snapshot
```

Candidate mirror: `data/research/s4_1_candidate_manager_commands.parquet` and
`data/research/s4_1_candidate_*`.

Guarantees: atomic writes via temp file + `os.replace`, metadata sidecar,
immutable prefix (existing rows are never rewritten), duplicate rejection by
`command_id`, per-timeframe cursor consumption.

Activation boundary: `data/trading/manager/activation.json`. Commands with an
`evaluation_timestamp` before the boundary carry the reason code
`BEFORE_ACTIVATION_BOUNDARY` and are never executed by a trader.

## 6. Trader contract

Each trader consumes only `timeframe == own timeframe`. Per cycle:

1. read pending commands for its own timeframe after the activation boundary;
2. skip commands already in `processed_command_ids` (idempotency);
3. inspect its own position;
4. apply the shared paper execution core;
5. append to its own signals / orders / fills / positions / trades;
6. persist its own controller state and runtime status.

One trader holds at most one open position. Up to four independent positions can
exist at the same time, one per timeframe.

## 7. Independent books

```text
data/trading/timeframe_traders/<TF>/signals.parquet
data/trading/timeframe_traders/<TF>/orders.parquet
data/trading/timeframe_traders/<TF>/fills.parquet
data/trading/timeframe_traders/<TF>/positions.parquet
data/trading/timeframe_traders/<TF>/trades.parquet
data/trading/timeframe_traders/<TF>/controller_state.json
data/trading/timeframe_traders/<TF>/runtime_status.json
data/trading/timeframe_traders/<TF>/*.meta.json
```

`<TF>` is one of `M15 M30 H1 H4`. There is no shared current-position dataset,
so a trader cannot overwrite another trader's position. Every row carries
`timeframe`, and IDs are timeframe-scoped:

```text
TF_SIGNAL_<TF>_<hash>   TF_ORDER_<TF>_<hash>   TF_FILL_<TF>_<hash>
TF_POSITION_<TF>_<hash> TF_TRADE_<TF>_<hash>
```

Aggregated views (`portfolio_summary.json`, OPS dashboard block) are derived and
read-only.

## 8. Lifecycle independence

The existing lifecycle contract is instantiated once per timeframe. Each
instance owns its episode ID, start timestamp, direction, phase, cooldown,
invalidation and state memory. An M15 invalidation cannot start, invalidate,
reset or block M30 / H1 / H4, and vice versa.

## 9. Fill contract

```text
LIVE1B-aligned execution fill (not next-candle close)
```

Entry and exit use execution-time BBO via the shared LIVE1B helper
`fill_price_for`:

- LONG ENTRY = ask, SHORT ENTRY = bid
- LONG EXIT = bid, SHORT EXIT = ask
- `opened_at` / fill timestamp = execution wall-clock at apply time
- `context_origin_price` is provenance only (never sizes or fills)

Forbidden: waiting for the next completed M15 bar close after the command,
same-bar OHLC look-ahead as a fill price, current mid fallback, fills shared
between traders, rewriting an entry or an exit. Missing/stale BBO means
`NO_FILL` (retry until TTL).

Causal ordering still requires `evaluation_timestamp <= execution_timestamp`.

## 10. Sizing and portfolio risk

From `config/timeframe_trader_risk.json`:

```text
deposit_usd            = 100000
portfolio_max_risk_pct = 1.0
portfolio_max_risk_usd = 1000
sizing_method          = RISK_BASED_STOP_LOSS_COST_AWARE
cost_aware_stop_sizing = true
fixed_notional_used    = false
entry_fee_rate_pct     = 0.02
exit_fee_rate_pct      = 0.05
weights                = M15 0.25, M30 0.25, H1 0.25, H4 0.25
per-trader cap         = 250 USD
aggregate cap          = 1000 USD
```

Risk is aggregated gross (`GROSS_NO_NETTING`): an M15 LONG risk and an H1 SHORT
risk add up. Unused risk is never reallocated between traders.

Rejections: `PORTFOLIO_RISK_LIMIT`, `TRADER_RISK_LIMIT`, `INVALID_STOP_DISTANCE`
— each produces a command with `action_allowed = false` and no order.

## 11. Opposite-position invariant

`M15 = OPEN_LONG` and `H1 = OPEN_SHORT` must result in two simultaneously open
positions with distinct position IDs, distinct entry prices, distinct stop
references, separate P&L, independent closes and independent restart recovery.
Netting to FLAT, merging into one net position, and one trader closing another
trader's position are all forbidden. `net_notional` is reporting only.

## 12. Processes

```text
timeframe_manager   scripts/live/timeframe_manager_daemon.py
trader_M15/M30/H1/H4 scripts/live/timeframe_trader_daemon.py --timeframe <TF>
control             scripts/timeframe_trading_ctl.sh {start|stop|restart|status|tail} [all|manager|traders|<TF>]
locks               data/runtime/locks/<role>.pid
logs                logs/<role>.log
```

Each role: one PID, one lock, own log, repo venv, repo cwd, stale-PID recovery,
duplicate-writer detection. Restarting one trader must not stop the manager,
the pipeline, the context refresher or the other traders. A manager restart must
not create duplicate commands.

## 13. Legacy migration

The legacy global paper controller and its ledger are a read-only historical
book after cutover:

```text
data/archive/legacy_global_paper_ledger_<stamp>/
```

Legacy trades are never reassigned to timeframes. Legacy and new controllers
must never run concurrently. An open legacy position blocks activation with
`S4_ACTIVATION_BLOCKED_BY_LEGACY_OPEN_POSITION`; it is never closed artificially.

## 14. Invariants enforced by tests

```text
future_joins = 0
unclosed_bar_joins = 0
duplicate_commands = duplicate_signals = duplicate_orders = 0
duplicate_fills = duplicate_trades = 0
cross_trader_state_writes = 0
cross_trader_netting = 0
aggregate_risk_breaches = 0
pnl_reconciliation_errors = 0
exchange_calls = 0
real_execution = false
BTC_ML_CONTINUATION_PROGRESSION = 0
PRICE_GATE = OFF
```

Test suite: `tests/test_s4_1_manager_independent_timeframe_traders.py` (46 tests).
