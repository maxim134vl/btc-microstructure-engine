# VIS1C — OPS Trading Performance Truth Candidate

**Status:** `VIS1C_OPS_PERFORMANCE_TRUTH_CANDIDATE_READY`  
**Branch:** `memory/canonical-system`  
**Basis:** `VIS1B_CANONICAL_PERFORMANCE_TRUTH_CANDIDATE_READY` (`f6d16a6`)  
**Adapter (unchanged):** `src/btc_ml/trading/trading_performance_truth.py`  
**OPS wiring:** `ops_dashboard_runtime_truth.py`  
**Evidence:** `data/candidate/architecture_recovery/vis1c_ops_trading_performance_truth/`  
**Mode:** `paper_only=true` · real execution disabled · **OPS API not restarted**

---

## A. Result

OPS Trading Operations now projects performance exclusively from `trading_performance_truth.py`. Old book-sum / manager-copy PnL calculator bypassed. Same-mark parity with the canonical adapter is **100%**. Risk, process, trader, and context sections remain independent. No process restarts; no live OPS cache writes.

---

## B. Production Scope

| Item | Path |
| ---- | ---- |
| Production (1) | `ops_dashboard_runtime_truth.py` |
| Tests (1) | `tests/test_vis1c_ops_trading_performance_truth.py` |
| Docs | `docs/audit/VIS1C_OPS_TRADING_PERFORMANCE_TRUTH_CANDIDATE.md` |

Unchanged: canonical adapter, manager, traders, books, risk resolver logic (VIS0), visualizer, OPS frontend.

---

## C. Baseline OPS Performance

Captured under `baseline/` before wiring.

| Field | OPS before | Canonical | Match |
| ----- | ---------- | --------- | ----- |
| realised (net) | book `net_pnl_usd` sum | adapter | values could match coincidentally |
| unrealised | manager trader sum | adapter GROSS | values could match |
| closed count | `len(trades.parquet)` | lineage-filtered | may diverge |
| fees / metrics / sample | not exposed | adapter | N/A |

Baseline proved OPS still owned a **parallel calculator**. Candidate removes it.

Live snapshot at candidate capture (dynamic mark): closed **7**, open **3**, realised net ≈ **62.09**, unrealised gross dynamic.

---

## D. Canonical Adapter Wiring

```text
TF books + manager mark
→ build_trading_performance_truth()
→ project_trading_performance_for_ops()
→ trading_operations.performance
→ apply_performance_aliases_to_timeframe_traders()
→ timeframe_traders.portfolio.realized_pnl / unrealized_pnl (aliases)
```

Import: `_build_canonical_trading_performance_truth`.

---

## E. Old Calculator Removal/Bypass

Removed from `build_timeframe_traders`:

- summing `trades.parquet` `net_pnl_usd`
- copying manager `unrealized_pnl_usd` into OPS cards
- portfolio `realized_total` / `unrealized_total` accumulators

Books still supply process/side/open position display and VIS0 risk attribution only.

---

## F. Source Policy

`performance.source` exposes adapter path, schema version, mark source/timestamp, `mtm_basis=GROSS_UNREALISED`, included/excluded sources.

Excluded: `RESEARCH_BAR_POLICY`, `LEGACY_PAPER_CONTROLLER`, `DASHBOARD_DERIVATION`, `QUARANTINE_BACKUP`.  
Contamination regression: closed count = canonical only; research/legacy counts informational.

---

## G. Portfolio Summary

From adapter via projection (null preserved, never coerced to 0):

```text
initial / closed / MTM equity
realised gross+net
unrealised gross+net
total gross+net
fees / slippage
open_position_count / closed_trade_count
```

Frontend aliases: `realized_pnl` ← realised net; `unrealized_pnl` ← unrealised gross.

---

## H. Per-Timeframe Summary

M15/M30/H1/H4 cards overlay adapter performance fields while keeping process + reserved risk.

Episode **743** retained as three distinct TF closed entities (M15/M30/H1).

---

## I. Equity

`initial_equity_usd`, `closed_equity_usd`, `mark_to_market_equity_usd` aliased from adapter (`mtm_basis=GROSS_UNREALISED`).

---

## J. Fees and Slippage

Portfolio and per-TF `total_fees_usd` / `total_slippage_usd` from adapter only.

---

## K. Descriptive Metrics

Wins/losses/win_rate/profit_factor/expectancy/holding — statuses from adapter. At current n&lt;30: **PRELIMINARY** / **INSUFFICIENT_SAMPLE**. Not decision-grade.

---

## L. Risk-Adjusted Metrics

Sharpe / Calmar / max drawdown / annualised return: `value=null` + status/reason. Never NaN/Inf/0.

---

## M. Sample Quality

```text
sample_quality.sample_status = PRELIMINARY (adapter)
descriptive_metrics_status / risk_adjusted_metrics_status / reasons
observation_start / observation_end from adapter closed tips
```

OPS does not set `DECISION_GRADE`.

---

## N. Data Quality

Informational block mirrors adapter (`excluded_research_count=11`, `excluded_legacy_count=4`, reconciliation, mark_status). Does not force global System Health degraded.

---

## O. Section Isolation

Performance adapter failure → `section_errors.trading_performance` + `trading_operations.performance.status=UNKNOWN` + PnL aliases null. Process / risk / traders / context / pipeline remain.

---

## P. Schema Compatibility

- Existing frontend fields kept: `portfolio.realized_pnl`, `unrealized_pnl`, per-TF `realized_pnl_usd` / `unrealized_pnl_usd` / `open_position_count`.
- New: `trading_operations.{manager,risk,performance}` (UI may ignore until later).
- `usd()` already maps null → `—`.
- No OPS frontend change required.

---

## Q. Canonical Parity

Same-mark comparison (adapter payload reused; no second mark read):

| Gate | Result |
| ---- | ------ |
| closed / open counts | 100% |
| realised gross/net | 100% |
| unrealised gross/net | 100% |
| fees / slippage | 100% |
| per-TF | 100% |
| sample / data-quality | 100% |

---

## R. Tests

```text
tests/test_vis1c_ops_trading_performance_truth.py
+ VIS1B + VIS0B + OPS1B + patch4.2
→ relevant failed = 0
```

---

## S. Git

Local commit only (no Gitea/GitHub push):

```text
feat: expose canonical trading performance in OPS
```

---

## T. Compliance

```text
production files changed = 1 (<=2)
test files changed = 1 (<=2)
canonical adapter changes = 0
manager/trader/book/visualizer/frontend = 0
process restarts = 0
live writes / trading writes / backfills = 0
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

---

## U. Next Step

After accept:

```text
VIS1D — controlled OPS API-only activation
```

Restart **only** OPS API; verify live canonical PnL; three polls + one natural M15 bar; confirm no core/trader restarts. Only then `VIS2A` timeframe charts candidate.
