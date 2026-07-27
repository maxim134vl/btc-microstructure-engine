# VIS0B — Canonical Trading Risk OPS Adapter Candidate

**Status:** `VIS0B_CANONICAL_RISK_ADAPTER_CANDIDATE_READY`  
**Note:** `VIS0B_FRONTEND_SEMANTICS_FOLLOWUP_REQUIRED` (null already renders as `—`; status/reason not shown — out of scope)  
**Basis:** `VIS0A_TRADE_RISK_VISUAL_TRUTH_PROVEN`  
**Evidence:** `data/candidate/architecture_recovery/vis0b_canonical_trading_risk_ops_adapter/`

---

## A. Result

OPS risk adapter now reads **manager `portfolio_summary.json`** (same reserved-risk truth as the entry gate). Missing `positions.risk_amount_usd` no longer becomes `$0.00`. Aggregate and per-TF parity with manager = **100%**. Manager/trader logic and books unchanged. OPS API **not** restarted (candidate only).

---

## B. Baseline Reproduction

| Field | OPS before | Manager truth |
| ----- | ---------: | ------------: |
| Gross / reserved open risk | **0.00** | **1000.00** |
| Available risk | **1000.00** | **0.00** |
| Open positions | 4 | 4 |
| Per-TF risk | 0.00 × 4 | 250.00 × 4 |

`baseline_mismatch_reproduced = true` → artifacts under `baseline/`.

---

## C. Canonical Manager Risk Source

| Item | Value |
| ---- | ----- |
| Artifact | `data/trading/manager/portfolio_summary.json` |
| Producer | `TimeframeManager.portfolio_summary()` ← `PaperTraderEngine.snapshot()["open_risk_usd"]` |
| Snapshot formula | `metadata_json.approved_risk_usd` on open position |
| Gate consumer | `TimeframeManager.run_cycle` via `open_risk` / `PortfolioRisk` |
| Cadence | manager daemon ~60s |
| Aggregate fields | `gross_open_risk_usd`, `available_risk_usd`, `portfolio_max_risk_usd`, `open_positions` |
| Per-TF field | `traders[TF].open_risk_usd` |

Chain:

```text
open position metadata.approved_risk_usd
→ PaperTraderEngine.snapshot open_risk_usd
→ TimeframeManager.portfolio_summary gross/available
→ entry decision (PortfolioRisk)
```

OPS is a **read-only** Level-1/2 consumer of that artifact.

---

## D. Risk Semantics

**OPS `risk` = `reserved_open_risk`** (approved risk reserved for the open position / portfolio budget usage).

Not shown as OPS primary risk:

- mark-to-market risk  
- offline `|entry−stop|×qty`  
- unrealized PnL  

Stop/qty appear in verification tables only as reference.

---

## E. Aggregate Risk Adapter

Candidate portfolio payload includes:

```text
max_risk_usd / portfolio_max_risk_usd
reserved_open_risk_usd / gross_open_risk_usd
available_risk_usd
risk_utilisation_pct
open_position_count / open_positions
risk_source / risk_source_tip / risk_status / risk_freshness
```

Uses manager fields directly (does not recompute a new formula). Invariant under current manager contract:

```text
available ≈ max − reserved
```

---

## F. Per-Timeframe Attribution

Precedence:

1. `portfolio_summary.traders[TF].open_risk_usd` (Level 2)  
2. `position.metadata_json.approved_risk_usd` (Level 3 — same as engine snapshot)  
3. `null` + `ATTRIBUTION_UNAVAILABLE` (never open+missing→0)

Live candidate: all four TFs **AVAILABLE** at **250.0**.

---

## G. Missing-Value Policy

| Case | value | status |
| ---- | ----: | ------ |
| Proven flat / zero reserved | 0.0 | `ZERO_CONFIRMED` |
| Aggregate source missing | null | `SOURCE_UNAVAILABLE` |
| Source stale | null | `SOURCE_STALE` |
| Open + no attribution | null | `ATTRIBUTION_UNAVAILABLE` |
| Proven number | numeric | `AVAILABLE` |

---

## H. Open Position Verification

| TF | Position ID | Entry | Stop (ref) | Qty | Canonical reserved | OPS candidate |
| -- | ----------- | ----: | ---------: | --: | -----------------: | ------------: |
| M15 | TF_POSITION_M15_* | 64662.72 | 64016.09 | 0.3365 | 250.0 | 250.0 |
| M30 | TF_POSITION_M30_* | 64662.72 | 64016.09 | 0.3365 | 250.0 | 250.0 |
| H1 | TF_POSITION_H1_* | 64698.10 | 64051.12 | 0.3363 | 250.0 | 250.0 |
| H4 | TF_POSITION_H4_* | 65227.32 | 64575.05 | 0.3336 | 250.0 | 250.0 |

(Exact IDs in `candidate/` / `open_position_verification.json`.)

---

## I. Staleness Contract

| Freshness | Meaning |
| --------- | ------- |
| `FRESH` | manager tip ≤ 30 min |
| `CARRIED_FORWARD` | tip ≤ 2 h |
| `STALE` | tip > 2 h → values nulled |
| `UNAVAILABLE` | no tip |

Unchanged open positions across bars do **not** alone mark risk stale.

---

## J. Canonical Parity

| Metric | Parity |
| ------ | -----: |
| max risk | 100% |
| reserved / gross open risk | 100% |
| available risk | 100% |
| open count | 100% |
| per-TF reserved (all 4) | 100% |

Baseline OPS gross **0 →** candidate **1000** (= manager).

---

## K. Entry-Gate Preservation

```text
manager logic changes = 0
trader logic changes = 0
entry gate changes = 0
trading book writes = 0
OPS adapter = read-only consumer
```

Production change limited to `ops_dashboard_runtime_truth.py`.

---

## L. OPS Health Semantics

| Condition | observability_health |
| --------- | -------------------- |
| Aggregate manager risk missing/stale | `DEGRADED_OBSERVABILITY` |
| Aggregate OK, some TF attribution gaps | `OPERATIONAL_WITH_LIMITATIONS` |
| Aggregate + TF OK | `OPERATIONAL` |

Global health policy file not modified (deferred).

**Frontend:** `usd(null)` → `—` already. Status/reason strings not rendered → follow-up `VIS0B_FRONTEND_SEMANTICS_FOLLOWUP_REQUIRED` (no VIS0B scope expansion).

---

## M. Tests

`tests/test_vis0b_canonical_trading_risk_ops_adapter.py` + regression suites:

```text
tests/test_vis0b_canonical_trading_risk_ops_adapter.py
tests/test_ops1b_live_operations_truth_candidate.py
tests/test_patch4_2_ops_dashboard_runtime_truth.py
→ 66 passed
```

---

## N. Production Scope

| Item | Count |
| ---- | ----: |
| Production files | 1 (`ops_dashboard_runtime_truth.py`) |
| Test files | 1 |
| Manager / trader / books / visualizer / OPS UI | 0 |

---

## O. Git

Local commit message:

```text
fix: expose canonical manager risk in OPS
```

No Gitea/GitHub push. No amend.

---

## P. Compliance

```text
production files changed <= 2   (1)
manager changes = 0
trader changes = 0
trading book schema changes = 0
visualizer changes = 0
OPS frontend changes = 0
process restarts = 0
live writes = 0
trading writes = 0
local commit = 1
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

Live PIDs at candidate time unchanged: pipeline `4618`, OPS `28285`, manager `61283`, traders `61284–61287`.

---

## Q. Next Step

```text
VIS0C — controlled OPS API-only activation
```

After live risk parity confirmation:

```text
VIS1A — canonical PnL and trade-history reconciliation
```

---

## Final status

```text
VIS0B_CANONICAL_RISK_ADAPTER_CANDIDATE_READY
```
