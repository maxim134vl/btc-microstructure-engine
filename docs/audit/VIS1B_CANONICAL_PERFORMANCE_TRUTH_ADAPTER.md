# VIS1B — Canonical Performance Truth Adapter Candidate

**Status:** `VIS1B_CANONICAL_PERFORMANCE_TRUTH_CANDIDATE_READY`  
**Branch:** `memory/canonical-system`  
**Basis:** `VIS1A_CANONICAL_PNL_TRADE_HISTORY_PROVEN`  
**Module:** `src/btc_ml/trading/trading_performance_truth.py`  
**Evidence:** `data/candidate/architecture_recovery/vis1b_canonical_performance_truth_adapter/`  
**Tests:** 76 passed (VIS1B + VIS0B + OPS1B + patch4.2)

---

## A. Result

One read-only adapter builds `trading_performance_truth` from S4.1 TF books + manager mark. Research/legacy/dashboard sources excluded. Live parity with manager/OPS: closed **6**, open **4**, realised/unrealised/fees **100%**. Sharpe/Calmar/annualised return `null` + insufficient status. No process restarts; no live OPS writes.

---

## B. Production Scope

| Item | Path |
| ---- | ---- |
| Production (1) | `src/btc_ml/trading/trading_performance_truth.py` |
| Tests (1) | `tests/test_vis1b_canonical_performance_truth_adapter.py` |
| Docs | `docs/audit/VIS1B_CANONICAL_PERFORMANCE_TRUTH_ADAPTER.md` |

Manager/traders/books/visualizer/OPS frontend unchanged.

---

## C. Canonical Source Policy

Reads only:

```text
data/trading/timeframe_traders/{M15,M30,H1,H4}/{signals,orders,fills,positions,trades}.parquet
data/trading/manager/portfolio_summary.json  # mark / reconciliation only
```

Entry point: `build_trading_performance_truth()`.

---

## D. Excluded Sources

```text
RESEARCH_BAR_POLICY
LEGACY_PAPER_CONTROLLER
DASHBOARD_DERIVATION
QUARANTINE_BACKUP
```

Contamination fixture: 6 canonical closed remain 6 even when research/legacy files exist on disk (never read).

---

## E. Identity and Lineage

Closed require `lineage_status=COMPLETE` (signal→order→entry fill→exit fill→trade).  
Open require `OPEN_COMPLETE`.  
Identity keys: `timeframe+trade_id` / `timeframe+position_id`.  
`episode_id` / CTX is **not** a trade id.

---

## F. Multi-Timeframe Semantics

Episode **743** × M15/M30/H1 retained as three distinct entities (`VALID_MULTI_TF_POSITIONS`). Same `trade_id` twice in one TF increments `duplicate_count` and is rejected from totals.

---

## G. Realised PnL

Uses stored `gross_pnl_usd` / `net_pnl_usd` / fees / slippage from trades; per-side fee/slip components from `closed_trade_economics` (canonical paper economics). Recompute parity **100%**.

---

## H. Unrealised PnL

```text
mark_source = manager.portfolio_summary.mark_price
gross_unrealised = LONG (mark−entry)×qty / SHORT (entry−mark)×qty
net_unrealised = gross − estimated exit fee − estimated exit slippage
```

Missing mark → unrealised `null`, `MARK_UNAVAILABLE` (never `0`).

---

## I. Fees and Slippage

Contract rates from `paper_trade_economics` (entry 2 bps, exit 5 bps, slippage enabled). Stored aggregates preferred for totals; derivation for per-side breakdown.

---

## J. Portfolio Aggregation

```text
portfolio = M15 + M30 + H1 + H4
```

Fields: realised/unrealised gross+net, fees, slippage, equity, counts.

---

## K. Per-Timeframe Aggregation

Each TF: closed/open counts, wins/losses, realised/unrealised, fees/slippage, tips.

---

## L. Equity

```text
initial_equity = INITIAL_CAPITAL_USD (100000)
closed_equity = initial + realised_net
mark_to_market_equity = closed_equity + unrealised_gross
mtm_basis = GROSS_UNREALISED
```

(`mtm_basis_alt_net_field` documents net-after-estimated-exit separately.)

---

## M. Descriptive Metrics

Counts, WR, gross profit/loss, avg win/loss, hold time available.  
`profit_factor` / `expectancy`: computed when finite, status **`PRELIMINARY`** + `INSUFFICIENT_SAMPLE` (n=6). No Infinity.

---

## N. Risk-Adjusted Metrics

```text
sharpe / calmar / max_drawdown / annualised_return = null
status = INSUFFICIENT_SAMPLE | INSUFFICIENT_HISTORY
decision_grade = false
```

---

## O. Sample Status

```text
descriptive = PRELIMINARY
risk_adjusted = INSUFFICIENT_SAMPLE
```

---

## P. Data Quality

Emits duplicate/orphan/incomplete counts, excluded research/legacy counts (defaults 11/4), mark + reconciliation status.

---

## Q. Canonical Payload

Schema `trading_performance_truth_v1` via `build_trading_performance_truth` / `write_candidate_artifacts` (candidate dir only).

---

## R. Parity (candidate run)

| Gate | Result |
| ---- | -----: |
| closed count | 6 |
| open count | 100% vs manager/OPS |
| realised | 100% |
| unrealised gross | 100% |
| per-TF | 100% |
| fees recompute | 100% |

(Dynamic mark — absolute unrealised USD follows live `mark_price`.)

---

## S. Tests

```text
tests/test_vis1b_canonical_performance_truth_adapter.py
+ VIS0B + OPS1B + patch4.2
→ 76 passed
```

---

## T. Git

```text
feat: add canonical trading performance truth
```

Local commit only. No push.

---

## U. Compliance

```text
production files = 1
test files = 1
manager/trader/book/visualizer/OPS frontend changes = 0
process restarts = 0
live/trading writes = 0
Gitea/GitHub push = NOT PERFORMED
```

---

## V. Next Step

```text
VIS1C — OPS Trading Operations performance-truth candidate/activation
```

Wire this adapter into OPS Trading Operations. Do not change charts/visualizer until then.

---

## Final status

```text
VIS1B_CANONICAL_PERFORMANCE_TRUTH_CANDIDATE_READY
```
