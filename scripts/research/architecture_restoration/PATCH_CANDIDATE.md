# Runtime Patch Candidate — Additive Identity Only (NOT ACTIVATED)

## Proposed files (exact list)

| File | Change type | Purpose |
|---|---|---|
| `src/btc_ml/trading/command_bus.py` | Additive columns only | Extend `COMMAND_COLUMNS` with identity fields |
| `src/btc_ml/trading/timeframe_manager.py` | Additive field fill only | Pass through `decision_id` from exact decision lookup into new command rows |
| `src/btc_ml/trading/paper_trader_engine.py` | Additive field fill only | Stop aliasing `decision_id = command_id`; use `command.get("decision_id")` for new records |
| `src/btc_ml/trading/trader_book.py` (if column lists live here) | Additive columns | Allow optional identity columns on new order/fill/position/trade rows |

## Forbidden in this patch

- Any change to intent selection, risk approval, sizing, stop/take, entry/exit timing
- Rewriting historical command bus / ledger rows
- Daemon restarts / live activation

## Additive command fields (new rows only)

```text
decision_id
context_id
lifecycle_episode_id   # original lifecycle key when known (not rewritten)
canonical_episode_id
timeframe_episode_id
manager_command_id     # existing command_id
timeframe
command_action         # alias of intent (non-breaking)
command_reason         # alias of reason_codes
command_created_at     # alias of created_at
source_decision_timestamp
```

## Identity rules

1. `decision_id` comes only from `context_decision_log.decision_id`
2. Manager must not call `make_id` / hash to invent a decision id
3. Trader must write the same `decision_id` into signals/orders/fills/positions/trades
4. Legacy rows without the field remain readable → `LEGACY_NO_DECISION_ID`
5. Exact join for attachment: `(source_bar_open|source_bar_close|evaluation_timestamp, timeframe)` only

## Activation gate

```text
ELIGIBLE_COMMAND_MISSING must be 0 before activation
NO LIVE RESTART in Phase 2
```

Current audit: `ELIGIBLE_COMMAND_MISSING = 0` (all 58 CNP are pre-manager / action_allowed=false).

## Status

```text
PATCH APPLIED TO SOURCE — CONTROLLED LIVE ACTIVATION IN PROGRESS
```

Applied production files (identity only):

- `src/btc_ml/trading/command_bus.py`
- `src/btc_ml/trading/timeframe_manager.py`
- `src/btc_ml/trading/paper_trader_engine.py`
- `src/btc_ml/trading/trader_book.py`

Lookup contract (fail-closed):

- open keys = `(candle_timestamp, timeframe)`
- close keys = `(candle_close_time_utc, timeframe)`
- `EXACT_UNIQUE_MATCH` → passthrough `decision_id`
- `NO_EXACT_DECISION_MATCH` → `decision_id = null`
- `AMBIGUOUS_EXACT_DECISION_MATCH` → `decision_id = null` (never first/last)

Tests: `tests/test_decision_lineage_passthrough.py`
