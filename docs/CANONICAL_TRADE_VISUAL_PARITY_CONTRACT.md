# Canonical Trade Visual Parity Contract

Status: `ACTIVE`
Schema: `canonical_visual_trade_view_v1`
Economics: `CANONICAL_PAPER_TRADE_ECONOMICS_V1`

## 1. Purpose

The trade chart renders the canonical trading book. It does not render research
restatements, and it does not compute trade economics of its own.

## 2. Primary source

```text
data/research/paper_simulator/canonical_visual_trade_view.parquet
```

Built by `src/btc_ml/visual/canonical_trade_view.py` as a deterministic union:

```text
archived legacy closed controller trades   (exit < S4 activation boundary)
+ timeframe trader closed trades           (entry >= S4 activation boundary)
= one read-only visual history
```

The activation boundary is read from `data/trading/manager/activation.json`; it is
never hardcoded.

### Inclusion rules

| Rule | Reason |
| --- | --- |
| Legacy `PAPER_POSITION_CTRL_*`, status `CLOSED` | controller-managed canonical history |
| Legacy `PAPER_POSITION_ONE_SHOT_*` excluded | manual probes, excluded from render before S4.1 and still excluded |
| Trader-book rows with an `exit_ts` | an open position is a position, never a closed-trade marker |
| Deduplicated on `visual_trade_id` | one trade can not appear twice |

## 3. Secondary research layer

```text
data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet
```

Retained and published in the payload as `secondary_research_layer`. It is a
research restatement over context episodes, so it must never be the primary
source. Nothing was deleted when it was demoted.

## 4. Row contract

`visual_trade_id`, `source_trade_id`, `source_book`, `source_schema_version`,
`asset`, `timeframe`, `side`, `entry_timestamp`, `exit_timestamp`, `entry_price`,
`exit_price`, `quantity`, `gross_pnl`, `fees_paid`, `slippage_paid`, `net_pnl`,
`context_episode_id`, `lifecycle_episode_id`, `manager_command_id`, `position_id`,
`economics_version`, `lineage_status`, `activation_epoch`.

Legacy rows carry `timeframe = LEGACY_GLOBAL` and `manager_command_id = null`.
The pre-S4 global book has no proven per-timeframe lineage, so it is not
retro-labelled.

## 5. Economics

`CANONICAL_PAPER_TRADE_ECONOMICS_V1`, defined by
`scripts/live/paper_trade_economics.py` and shared by the S4 execution core, the
production ledgers and the visual layer.

```text
gross_pnl - fees_paid - slippage_paid == net_pnl
```

The render path copies these settled values (`copied_canonical_economics = true`)
instead of deriving them from prices. `POLICY_CONTEXT_EVENT_PRICED_PNL` is the
deprecated predecessor and is not a valid expectation for the production payload.

## 6. Context lineage

`context_episode_id` is resolved point-in-time from
`data/cognition/market_context_lifecycle_memory.parquet`: the episode already
active at the trade's entry timestamp. A later episode can never be attached.

## 7. Invariants

```text
duplicate_visual_trade_ids      = 0
cutover_overlap                 = 0
future_context_joins            = 0
future_trade_joins              = 0
unclosed_positions_as_trades    = 0
pnl_reconciliation_errors       = 0
legacy_archive_mutations        = 0
```

## 8. Test contract

`tests/test_patch4_3_trade_visual_runtime_parity.py` asserts these semantically.
Live context episode numbers and trade counts must never be hardcoded in live or
parity tests: a new trade or a new episode must not break a test. Fully synthetic
fixtures may still pin their own identifiers.
