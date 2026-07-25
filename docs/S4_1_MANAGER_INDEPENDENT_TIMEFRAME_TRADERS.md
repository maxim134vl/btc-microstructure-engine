# S4.1 — Manager and Independent Timeframe Traders

**Status:** `S4_MANAGER_TRADER_ARCHITECTURE_ACTIVATED`
**Branch:** `memory/canonical-system`
**Activation timestamp:** `2026-07-24T20:20:14.398043Z`
**Activation stamp:** `20260724_202010`

---

## A. Result

The single global decision stream → single paper controller → single global position constraint is removed.

Production paper runtime now executes as:

```text
canonical runtime
→ timeframe state bus (M15/M30/H1/H4)
→ deterministic manager
→ per-timeframe command
→ four independent traders with independent books
```

Four independent positions can exist simultaneously with no netting between timeframes.

D1 has no trader (`TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER`).

---

## B. Architecture

| Component | Module | Role |
| --- | --- | --- |
| Timeframe state adapter | `src/btc_ml/trading/timeframe_state_adapter.py` | Per-timeframe point-in-time state, `source_bar_close <= evaluation_timestamp` |
| Manager | `src/btc_ml/trading/timeframe_manager.py` | Deterministic dispatcher, one command per timeframe |
| Command bus | `src/btc_ml/trading/command_bus.py` | Append-only, atomic, deterministic IDs, per-timeframe cursors |
| Portfolio risk | `src/btc_ml/trading/portfolio_risk.py` | Per-trader and gross aggregate limits, no netting |
| Shared execution core | `src/btc_ml/trading/paper_trader_engine.py`, `paper_core.py` | One execution implementation for all traders |
| Trader | `src/btc_ml/trading/timeframe_trader.py`, `trader_book.py` | Reads only own commands, owns only own book |
| Process locks | `src/btc_ml/trading/process_lock.py` | PID/lock, zombie + stale PID recovery |
| Activation | `src/btc_ml/trading/activation.py` | Gates, legacy migration, cutover record |

Daemons:

```text
scripts/live/timeframe_manager_daemon.py
scripts/live/timeframe_trader_daemon.py --timeframe {M15|M30|H1|H4}
```

---

## C. Shared Execution Core

No second execution engine was written. The proven logic from the repaired paper controller is reused through one core:

```text
core_version           shared_paper_execution_core_v1
economics_source       canonical_paper_trade_economics_v1
sizing_method          risk_based_stop_loss_cost_aware
initial_capital_usd    100000.0
max_risk_usd           1000.0
entry_fee_bps          2.0
exit_fee_bps           5.0
entry_slippage_bps     3.0
exit_slippage_bps      3.0
stop_exit_slippage_bps 5.0
execution_enabled      false
```

Sources reused: `scripts/live/paper_trade_economics.py` and the repaired
`bounded_paper_trading_controller_auto_ledger_no_real_execution.py` semantics.
Signal generation, order intent, point-in-time fill, position state, exit
processing, cost-aware sizing, fees, slippage, gross/net P&L and idempotency
have a single implementation shared by all four traders.

---

## D. Command Contract

Schema: `timeframe_manager_command_v1` — see `docs/CANONICAL_MANAGER_TRADER_CONTRACT.md`.

Bus columns (35):

```text
command_id, manager_cycle_id, schema_version, asset, timeframe,
evaluation_timestamp, source_bar_open, source_bar_close,
source_state_timestamp, source_event_timestamp,
timeframe_state, timeframe_direction, availability_status,
lifecycle_episode_id, lifecycle_phase,
intent, action_allowed, reason_codes, exit_reason,
confidence, alignment_score, persistence_score, structural_rank, location_bias,
requested_risk_usd, approved_risk_usd, portfolio_open_risk_usd,
stop_reference, invalidation_reference, command_ttl_seconds,
cross_timeframe_metadata, created_at, source_lineage,
paper_only, execution_enabled
```

Intents: `OPEN_LONG`, `OPEN_SHORT`, `HOLD`, `CLOSE`, `NO_ACTION`.

Deterministic key:

```text
asset + timeframe + evaluation_timestamp + lifecycle_episode_id + intent
```

Commands are immutable; a repeated manager cycle produces no duplicate rows.
Cross-timeframe information is carried only in `cross_timeframe_metadata` and is
never a directional veto.

---

## E. Independent Lifecycle

Each timeframe runs its own instance of the existing lifecycle contract with its
own episode ID (`M15:740`, `M30:740`, `H1:740`, `H4:740` at the current tip),
start timestamp, direction, cooldown, invalidation and phase.

M15 state cannot start, invalidate, reset or block any other timeframe. Lifecycle
rules are unchanged — they are applied independently four times.

---

## F. Independent Books

```text
data/trading/manager/timeframe_command_memory.parquet   (+ .meta.json)
data/trading/manager/manager_state.json
data/trading/manager/portfolio_summary.json
data/trading/manager/activation.json
data/trading/manager/legacy_migration.json
data/runtime/timeframe_manager_latest.json

data/trading/timeframe_traders/{M15,M30,H1,H4}/
    signals.parquet
    orders.parquet
    fills.parquet
    positions.parquet
    trades.parquet
    controller_state.json
    runtime_status.json
    metadata sidecars
```

Every ID and lineage field carries the timeframe. There is no shared current-position
parquet. The portfolio summary is a derived read-only read-model.

---

## G. Opposite Positions

Artifact: `data/research/s4_1_opposite_positions_proof.json` — `passed: true`.

| | M15 | H1 |
| --- | --- | --- |
| position_id | `TF_POSITION_M15_b0d9636c4366c639` | `TF_POSITION_H1_0808f768fc5ed70e` |
| direction | LONG | SHORT |
| entry_price | 60100.0 | 60200.0 |
| stop_reference | 59499.0 | 60802.0 |
| approved_risk_usd | 250.0 | 250.0 |

Verified: both open simultaneously, distinct IDs, distinct entry prices, distinct
stop references, separate books, gross risk 500 USD (not netted), both survive
restart, M15 closes independently while H1 stays open and untouched, one position
per trader.

Candidate replay additionally produced **6** natural cycles with genuinely opposite
directions, e.g. `2026-07-24T02:45:00Z` → `M15 LONG / M30 LONG / H1 LONG / H4 SHORT`.

---

## H. Portfolio Risk

Config: `config/timeframe_trader_risk.json` (`timeframe_trader_risk_v1`).

```text
deposit_usd             100000
portfolio_max_risk_pct  1.0
portfolio_max_risk_usd  1000
weights                 M15/M30/H1/H4 = 0.25 each
per_trader_max_risk_usd 250 each
risk_aggregation        GROSS_NO_NETTING
auto_reallocation       false
```

Rejections: `PORTFOLIO_RISK_LIMIT`, `TRADER_RISK_LIMIT`, `INVALID_STOP_DISTANCE`.
Opposing exposures add to gross open risk; they never offset.

---

## I. Fill and P&L

`command evaluation_timestamp < fill market timestamp` is enforced; no same-bar
look-ahead, no future join, no current-price fallback, no shared fill between
traders, no entry/exit rewriting. Absence of a valid observation yields `NO_FILL`.

Candidate replay invariants (108 cycles, 432 rows, window
`2026-07-23T17:15:00Z → 2026-07-24T20:00:00Z`):

```text
future_joins                    0
unclosed_bar_joins              0
duplicate_commands              0
duplicate_signals               0
duplicate_orders                0
duplicate_fills                 0
duplicate_trades                0
duplicate_positions             0
cross_trader_state_writes       0
traders_with_multiple_open_pos  0
aggregate_risk_breaches         0
```

P&L reconciliation: `data/research/s4_1_pnl_reconciliation.csv` — 17 rows, **0 mismatches**.

---

## J. Legacy Migration

Legacy mode at cutover: `CLOSED_HISTORY_ONLY` (7 positions, 0 open) → activation allowed.

```text
legacy_ledger_state = ARCHIVED_READ_ONLY
archive_dir         = data/archive/legacy_global_paper_ledger_20260724_202010
```

Archived read-only: signals, orders, trades, positions, events, equity curve,
risk blocks, controller actions/cycles (+ sidecars).

Legacy history was not reassigned to timeframes. New books start flat at the
activation boundary and only commands after that boundary are processed. The
legacy global paper controller is stopped and does not run alongside the traders.

---

## K. Processes

| Role | PID | State |
| --- | ---: | --- |
| timeframe_manager | 4958 | RUNNING |
| trader_M15 | 5028 | RUNNING |
| trader_M30 | 5085 | RUNNING |
| trader_H1 | 5130 | RUNNING |
| trader_H4 | 5182 | RUNNING |
| paper_controller (legacy) | — | STOPPED (required=false post-cutover) |

Unchanged model runtime: `live_feed 93404`, `canonical_pipeline 20041`,
`context_refresher 97695`, `dashboard_refresher 96805`.

Each S4 process has its own PID file, lock, log, repo interpreter and cwd, with
zombie detection, stale PID recovery and restart protection.

---

## L. Restart and Isolation

Artifact: `data/research/s4_1_restart_proof.json` — `passed: true`.

```text
manager_restart_no_duplicate_commands   true
command_bus_unique_ids                  true
single_trader_restart_isolated          true
single_trader_restart_no_reexecution    true
full_restart_books_stable               true
open_positions_preserved                true
four_books_restored                     true
duplicate_commands                      0
```

All four open position IDs are byte-identical before and after a full
manager + trader restart.

---

## M. OPS Dashboard

`ops_dashboard_runtime_truth.py` gained a `timeframe_traders` truth plane and
S4-aware process specs. After the S4.1 cutover the legacy `paper_controller`
becomes non-required and the manager plus four traders become required.

Live `GET /api/v1/ops/snapshot` after the OPS-backend-only restart:

```text
overall_health          HEALTHY_WITH_KNOWN_LIMITATIONS
processes               11 (manager + 4 traders present)
pipeline_engines        20 (unchanged)
command_bus.rows        12
duplicate_command_ids   0
portfolio open risk     0.00 / 1000.00
d1_trader               false
```

Frontend binding (data only):

| File | Change |
| --- | --- |
| `dashboard/frontend/src/types/ops.ts` | `RuntimeTruthTimeframeTraders` / trader / command-bus / portfolio types |
| `dashboard/frontend/src/components/ops/OpsDashboard.tsx` | Two cards inside the existing Runtime Truth grid: *Timeframe Traders* and *Manager / Portfolio* |

Both cards are built from the existing `PanelCard` / `ListRow` / `SectionLabel`
components with existing status tokens. Manager and the four traders also appear
automatically in the existing *Processes* card because it is data-driven.

Visual regression checks:

```text
CSS files changed                 0   (index.css, styles.css, lifecycle.css hash-pinned)
inline styles added               0   (count unchanged at 1, pre-existing progress bar)
stylesheet imports added          0
new component libraries           0
theme / font / color / grid       unchanged
```

Typecheck reports only pre-existing errors (unused symbols, missing
`lightweight-charts` dependency); the new bindings typecheck cleanly. The
prebuilt `dashboard/frontend/dist` (2026-07-11) was intentionally not rebuilt —
the bindings take effect on the next normal frontend start.

---

## M2. Natural Live Cycles

Artifact: `data/research/s4_1_live_cycles_20260724T211537.json` (observed without
forcing anything; the `21:15:00Z` cycle appeared live during the observation window).

| Evaluation | M15 | M30 | H1 | H4 | Open risk |
| --- | --- | --- | --- | --- | ---: |
| 2026-07-24T20:30:00Z | NO_ACTION | NO_ACTION | NO_ACTION | NO_ACTION | 0.00 |
| 2026-07-24T20:45:00Z | NO_ACTION | NO_ACTION | NO_ACTION | NO_ACTION | 0.00 |
| 2026-07-24T21:00:00Z | NO_ACTION | NO_ACTION | NO_ACTION | NO_ACTION | 0.00 |
| 2026-07-24T21:15:00Z | NO_ACTION | NO_ACTION | NO_ACTION | NO_ACTION | 0.00 |

```text
observed_cycles = 4
duplicates      = 0
```

Every timeframe receives its own explainable per-cycle result
(`NON_DIRECTIONAL_TIMEFRAME_STATE`). No trade is a valid outcome.

---

## N. Tests

`tests/test_s4_1_manager_independent_timeframe_traders.py` — **46 passed**,
covering the full required list: manager fan-out, per-timeframe state isolation,
absent D1 trader, no cross-timeframe fallback, event-sparse availability,
incomplete/future bar rejection, deterministic and idempotent command IDs,
per-trader command filtering, independent lifecycle, coexisting M15 LONG +
H1 SHORT, no netting, no cross-trader close, one position per trader, four
simultaneous positions, shared execution core, strict post-command fill, LONG and
SHORT P&L, fees, slippage, per-trader ≤250 USD, aggregate ≤1000 USD, gross opposing
risk, invalid stop and portfolio limit rejection, restart idempotency and
isolation, legacy blocking and cutover rules, write-plane isolation, no exchange,
`CONTINUATION` and `PRICE_GATE` off, dashboard visual preservation.

Combined regression run across the paper controller, fill/P&L, decision no-repaint,
lifecycle memory, context decision logger, risk-block, MTF, OPS dashboard
(Patch 4.1/4.2/4.3) and write-plane suites: **350 passed, 2 skipped, 0 failed**.

Two test contracts were reconciled with the cutover rather than worked around:

- `tests/test_patch2b3_paper_controller_production_activation.py::test_05` encoded
  the pre-S4 invariant "legacy controller is RUNNING". It now branches on the
  activation record and requires the legacy controller to be **stopped** after cutover.
- `test_46` previously froze the hash of `OpsDashboard.tsx` / `types/ops.ts`, which
  would forbid the data bindings §21 explicitly allows. Pure-visual files stay
  hash-pinned; the binding files are now policed by content rules (no inline styles
  added, no stylesheet imports, existing components only).

### Full-suite picture

A whole-repository run (`venv/bin/python -m pytest -q tests`) gives
**1970 passed, 109 failed, 2 skipped**, against a pre-S4.1-completion baseline of
101 failed. Diffed against that baseline:

**Fixed (6)** — three directly by this work:

```text
test_patch2b3::test_05_controller_running_one_pid_skip_refresh   (cutover-aware contract)
test_patch4_2::test_21_paper_stale_distinct_from_stopped         (S4-aware truth builder + backend restart)
test_patch4_2::test_29_decision_stale_degraded_contract          (same)
test_bounded_paper_trading_controller_auto_ledger::test_05
test_context_visual_trade_position_overlay::test_refresher_once_writes_visual_only
test_single_live_context_refresh_append_before_next_monitor_safety::test_01
```

**New (14)** — all inside the trade-chart / context-visualizer domain, none touching
S4 modules or the OPS dashboard bindings. They are data-drift failures in the layer
Patch 4.3 audited and deliberately left unactivated:

```text
chart source                     policy_context_canonical_bar_policy_trades.parquet
controller_ledger_used_for_render false
chart trade count                11   (tests pin 10)
hardcoded context IDs in tests   712, 721
live lifecycle episode now       740
```

Because `controller_ledger_used_for_render` is `false`, the chart never consumed the
legacy controller ledger, so stopping that controller at the cutover did not change
the chart's data source. The failures come from context episodes advancing past the
IDs and counts these tests hardcode — precisely the defect Patch 4.3 recorded. The
visual refresher itself runs healthy and visual-only (`visual_status=LIVE_OK`, no
ledger mutation), so there is no safety breach.

These are not repaired here: S4.1 forbids touching the market visualizer, and
repointing the chart at the real ledger is the Patch 4.3 parity-contract activation,
which is a separate, explicitly deferred stage.

One further pre-existing unrelated failure sits in the same domain:
`tests/test_detailed_pnl_container_sanity.py` expects the trade-chart payload to
report `POLICY_CONTEXT_EVENT_PRICED_PNL`, while the visual refresher (unchanged
since 2026-07-24 09:49, before S4.1) emits `CANONICAL_PAPER_TRADE_ECONOMICS_V1`.
This belongs to the Patch 4.3 trade-chart parity contract, which is deliberately
not activated; S4.1 forbids touching the chart.

`src/btc_ml/trading/activation.py` was hardened during this run:
`legacy_controller_pids()` now matches the production script path instead of the
bare filename, so sandboxed pytest copies are no longer mistaken for the retired
production controller.

---

## O. Preservation

Artifact: `data/research/s4_1_preservation_20260724_202010.json`.

Cognition, context, lifecycle and decision datasets are hash-recorded and
unchanged by the manager/trader plane. Visual invariant files are hash-pinned.
Feed, pipeline, context refresher and the MTF availability writer were not
restarted; only the OPS backend was restarted to publish the new read-model.

---

## P. Safety

- Paper only; `execution_enabled=false`, `exchange_enabled=false`, exchange calls 0
- Manager writes only the command bus and its own state
- Traders write only their own books
- No cognition / context / decision writes
- `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`
- No model semantic changes, no redesign, no commit/push

---

## Q. Current Capability

Confirmed. The production paper runtime can hold, simultaneously and independently:

```text
M15  LONG
M30  independent state
H1   SHORT
H4   independent state
```

with separate positions, orders, fills, trades, lifecycle episodes, controller
state, risk budgets and P&L, and with gross (never netted) portfolio risk.

At the current market tip all four timeframes report `OBSERVE` /
`NON_DIRECTIONAL`, so every command is `NO_ACTION` — an explainable per-timeframe
result, not a failure.

---

## Artifacts

```text
docs/S4_1_MANAGER_INDEPENDENT_TIMEFRAME_TRADERS.md
docs/CANONICAL_MANAGER_TRADER_CONTRACT.md
config/timeframe_trader_risk.json

data/research/s4_1_preflight_20260724_192526.json
data/research/s4_1_preflight_20260724_201325.json
data/research/s4_1_candidate_summary.json
data/research/s4_1_candidate_replay.parquet
data/research/s4_1_candidate_manager_commands.parquet
data/research/s4_1_candidate_portfolio_summary.json
data/research/s4_1_candidate_timeframe_traders/{M15,M30,H1,H4}
data/research/s4_1_opposite_positions_proof.json
data/research/s4_1_risk_reconciliation.csv
data/research/s4_1_pnl_reconciliation.csv
data/research/s4_1_restart_proof.json
data/research/s4_1_backup_manifest_20260724_202010.json
data/research/s4_1_production_backups_20260724_202010/
data/research/s4_1_activation_20260724_202010.json
data/research/s4_1_activation_summary_20260724_202010.json
data/research/s4_1_live_cycles_20260724T205603.json
data/research/s4_1_live_cycles_20260724T211537.json
data/research/s4_1_preservation_20260724_202010.json
data/archive/legacy_global_paper_ledger_20260724_202010/
```

## Next Step

Determined separately. Do not auto-start the next stage.
