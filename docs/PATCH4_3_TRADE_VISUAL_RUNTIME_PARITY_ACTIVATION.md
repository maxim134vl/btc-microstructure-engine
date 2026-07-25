# PATCH 4.3 — Trade Visual Runtime Parity Production Activation

Status: `PATCH4_3_TRADE_VISUAL_PARITY_ACTIVATED`
Branch: `memory/canonical-system`
Baseline: `S4_MANAGER_TRADER_ARCHITECTURE_ACTIVATED`

## A. Result

The trade chart is bound to the canonical trading book. Its economics are copied
from the settled ledger, its context identifiers are resolved point-in-time, and
its tests assert semantic invariants instead of a historical snapshot. The S4
manager–trader runtime was not touched.

## B. Root cause of the drift

The failing tests pinned a moment in time rather than a contract:

| Pinned value | Reality at activation |
| --- | --- |
| context IDs 712 / 721 | live lifecycle had advanced to 740 |
| trade count 10 / 11 | canonical book holds 4 closed trades |
| `POLICY_CONTEXT_EVENT_PRICED_PNL` | payload already emitted `CANONICAL_PAPER_TRADE_ECONOMICS_V1` |

The preflight snapshot taken before any edit
(`data/research/patch4_3_preflight_20260725_073822.json`) proves the economics
mode and the payload key set were already canonical, so those failures predate
this patch rather than being caused by it.

## C. Canonical visual source

Previously the chart's primary layer was
`policy_context_canonical_bar_policy_trades.parquet` — a research restatement
over context episodes that the Patch 4.3 audit had already classified as
`RESEARCH_POLICY_CONTEXT_NOT_PRODUCTION_LEDGER` and raised as an ERROR alert
(`CHART_SOURCE_NOT_PRODUCTION_LEDGER`).

The primary layer is now `canonical_visual_trade_view.parquet`, built by
`src/btc_ml/visual/canonical_trade_view.py`. The policy-context layer is retained
and published as `secondary_research_layer`, so no data was lost.

## D. Legacy / S4 cutover

```text
activation boundary = 2026-07-24T20:20:14.398043Z

legacy archived controller trades (exit < boundary)  → 4, timeframe LEGACY_GLOBAL
timeframe trader trades          (entry >= boundary) → 0, tail still empty
cutover_overlap                                       → 0
```

The legacy archive stays read-only (verified: no write bit on any archived
parquet). Legacy rows are not retro-labelled with a timeframe and carry a null
manager command ID.

## E. Context lineage

Episodes are resolved as-of the trade entry timestamp from the lifecycle memory:

| trade | context episode | entry |
| --- | ---: | --- |
| `VIS_PAPER_POSITION_CTRL_509972cf721bddda` | 709 | 2026-07-21T12:57:32Z |
| `VIS_PAPER_POSITION_CTRL_a6eeafaa83387e13` | 720 | 2026-07-22T13:51:04Z |
| `VIS_PAPER_POSITION_CTRL_fe27adfd50aa76fc` | 724 | 2026-07-23T07:17:57Z |
| `VIS_PAPER_POSITION_CTRL_d6b0e41e6feb3f7b` | 727 | 2026-07-23T11:42:03Z |

`future_context_joins = 0`. The dead production constant `LATEST_CONTEXT_ID = 721`
was removed from the refresher.

## F. Trade count

The payload count is derived from the canonical source, never asserted as a
literal. `visual_trade_overlay_count_expected == visual_trade_overlay_count_rendered
== len(canonical view)`, with `duplicate_visual_trade_ids = 0`.

## G. Economics

`CANONICAL_PAPER_TRADE_ECONOMICS_V1` is canonical: it is defined in
`scripts/live/paper_trade_economics.py` and shared by the S4 execution core, the
production ledgers and the visual layer. `POLICY_CONTEXT_EVENT_PRICED_PNL` is its
deprecated predecessor and the stale expectations were migrated.

The render path previously recomputed fees, slippage and P&L from prices. It now
copies the settled ledger values (`copied_canonical_economics = true`), so
`gross − fees − slippage == net` holds exactly for every rendered trade
(`pnl_reconciliation_errors = 0`).

## H. Candidate comparison

`data/research/patch4_3_current_vs_candidate.csv`

```text
EXPECTED_PRIMARY_SOURCE_SWAP     4
NO_DIVERGENCE                    3
EXPECTED_ECONOMICS_CONTRACT_FIX  1
EXPECTED_DEDUP_FIX               1
EXPECTED_S4_LINEAGE              1
EXPECTED_DYNAMIC_CONTEXT         1
UNEXPLAINED                      0
```

`EXPECTED_PRIMARY_SOURCE_SWAP` is an added classification: §15 did not anticipate
the primary layer changing source, so the swap was confirmed with the user before
activation rather than applied silently.

## I. Production activation

Changed:

| File | Change |
| --- | --- |
| `src/btc_ml/visual/canonical_trade_view.py` | new canonical read-only view builder |
| `src/btc_ml/visual/__init__.py` | package exports |
| `scripts/live/run_market_context_visual_refresher.py` | source repointed, ledger economics pass-through, lineage fields, dead `LATEST_CONTEXT_ID` removed |
| `scripts/ops/patch4_3_visual_parity_preflight.py` | preflight capture |
| `scripts/ops/patch4_3_visual_parity_candidate.py` | candidate + divergence classification |
| `scripts/ops/patch4_3_visual_parity_artifacts.py` | lineage, economics, no-lookahead, cutover proofs |
| `tests/test_patch4_3_trade_visual_runtime_parity.py` | new 39-check parity suite |

Only the visual refresher was restarted. Feed, pipeline, context refresher, OPS
backend, manager and all four traders kept their PIDs.

## J. Visual preservation

No CSS, HTML, font, colour, layout or chart-library change. `lifecycle.css`,
`index.html` and `lifecycle_app.js` were not modified by this patch. Only the
payload bindings changed; markers, tooltips, stop/take lines and the panel
geometry render exactly as before. Stop-loss and take-profit lines are visible on
all four rendered trades.

## K. Tests

```text
targeted parity suite   37 passed, 2 skipped
full repository suite   2018 passed, 100 failed, 4 skipped   (venv/bin/python)
baseline                1970 passed, 109 failed, 2 skipped
delta                   +48 passed, -9 failed
```

The two skips are the empty S4 tail and the absent CSS-hash baseline field.

Remaining failures by domain:

| Domain | Count | Cause |
| --- | ---: | --- |
| legacy paper preview / dry-run suites | ~50 | legacy controller retired at S4 cutover |
| stale research validation JSONs (22–23 Jul) | ~25 | audit snapshots not regenerated; keys absent |
| viewer HTML/CSS/JS text assertions | ~8 | frontend edits predating this patch |
| dead `visual_paper_trade_overlay_builder` keys | ~6 | keys removed by an earlier refactor |
| other unrelated (ops payload, metadata) | ~11 | outside the visual plane |

None are in the trade visual parity domain.

## L. Runtime preservation

```text
live_feed          93404  unchanged
canonical_pipeline 20041  unchanged
context_refresher  97695  unchanged
ops_backend        24661  unchanged
timeframe_manager   4958  unchanged
trader_M15          5028  unchanged
trader_M30          5085  unchanged
trader_H1           5130  unchanged
trader_H4           5182  unchanged
visual_refresher           restarted (allowed by §16)
```

## M. Safety

Visual plane only. No trading mutation, no exchange call, no real execution, no
S4 change, no commit or push. `real_execution = false`, `exchange_enabled = false`,
`BTC_ML_CONTINUATION_PROGRESSION = 0`, `PRICE_GATE = OFF`.

## N. Final health

```text
S4 manager–trader architecture   HEALTHY   manager + 4 traders running, books untouched
Trade visual parity              ALIGNED   LIVE_OK, canonical source, 0 unexplained divergences
OPS dashboard                    HEALTHY   backend PID unchanged, no binding change
Full repository suite            IMPROVED  109 -> 100 failures, no new domain
```
