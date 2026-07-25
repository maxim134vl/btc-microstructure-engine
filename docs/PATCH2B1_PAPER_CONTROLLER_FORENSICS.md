# PATCH 2B.1 — Paper Controller Forensics and Recovery Candidate

**Tag:** `20260724_143505`  
**Branch:** `memory/canonical-system`  
**Production paper controller:** not started  
**Production paper parquet:** unchanged (sha/mtime vs preflight)

---

## A. Result

```text
PAPER_CONTROLLER_REQUIRES_LOGIC_REPAIR
```

Not ready for live recovery. Blocking issues:

1. **PAPER_HIDDEN_CONTEXT_TRIGGER** — still owns context refresh + decision append  
2. Crash root cause on decision schema (`context_entered_at` Arrow type)  
3. Preview contract drift (hold mode / episode key) vs outdated tests  
4. Ledger P&L ≠ canonical `closed_trade_economics` (S1 accounting)

---

## B. Controller Root Cause

| Field | Value |
| --- | --- |
| Entrypoint | `scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py` |
| Ctl | `scripts/bounded_paper_trading_controller_ctl.sh` |
| Interpreter | `<repo>/venv/bin/python` |
| PID/lock | `run/bounded_paper_trading_controller_auto_ledger.{pid,lock}` → stale **25953** |
| Cadence | `--interval-seconds 900`, max 96 cycles / 24h |

**Classification:**

```text
CRASHED
+ DEPENDENCY_FAILURE
+ INTENTIONALLY_DISABLED
```

Last live error (`logs/bounded_paper_trading_controller_auto_ledger.log`, `2026-07-24T09:25:58Z`):

```text
ArrowTypeError: context_entered_at str cannot be converted to int
```

Stack: `run_one_cycle` → `refresh_and_maybe_append` → `append_decision` → `to_parquet`.

After Patch 1 / 2A the process was **intentionally left DEAD** (no restart policy while context ownership moved).

---

## C. Preview Test Failures

Artifact: `data/research/patch2b1_preview_test_failures.json`

### 1) `test_04_long_short_stop_take_context_and_stop_first`

| | |
| --- | --- |
| Expected | `PREVIEW_CLOSE_LONG_STOP_LOSS` |
| Actual | `PREVIEW_HOLD_LONG` |
| Classification | **ARCHITECTURAL_DRIFT** |

Default `PAPER_CONTEXT_HOLD_MODE = HOLD_UNTIL_DIRECTIONAL_CONTEXT_END` suppresses stop/take. With `hold_mode=OFF`, stop-first returns as the test expects. Test expectation is stale relative to intentional hold policy — **do not flip expectation without deciding production exit canon**.

### 2) `test_08_flat_entry_gate_and_synthetic_price_forbidden`

| | |
| --- | --- |
| Expected | `allowed=True` for minimal LONG_CONTEXT+CHALLENGED dict |
| Actual | `allowed=False`, `ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY` |
| Classification | **ARCHITECTURAL_DRIFT** |

Gate now requires episode key / fresh start / collection rules. Fixture is incomplete vs current production gate — not a reason to weaken the gate to “make the test pass.”

---

## D. Input Contract

Artifact: `data/research/patch2b1_decision_to_paper_contract.json`

| Field | Role |
| --- | --- |
| `candle_timestamp` | REQUIRED_GATE |
| decision action / side mapping | REQUIRED_GATE |
| `action_allowed` / stale / pipeline_pending | REQUIRED_GATE |
| `active_market_context` | REQUIRED_GATE |
| `lifecycle_state` | REQUIRED_GATE |
| context start / episode key | REQUIRED_GATE |
| `context_origin` | OPTIONAL_INPUT |
| edge / confidence | DIAGNOSTIC_ONLY |
| reinforcement / probabilistic / MTF / `auction_synthesis` | IGNORED (no direct read) |
| visual JSON | IGNORED |
| research edge lookup snapshot | OPTIONAL_INPUT on **hidden decision rebuild** path |

Canonical production reads: feed, decision log, lifecycle, final, auction_episode, cognitive, intrabar snapshot.

---

## E. Context Independence

```text
PAPER_HIDDEN_CONTEXT_TRIGGER
```

Every cycle (unless `--skip-refresh`) runs:

1. `run_live_context_refresh_once` / one-shot refresh  
2. shadow chain  
3. `append_decision` into production decision log  

Paper is **not** a read-only consumer. Production activation is forbidden until ownership becomes:

```text
PAPER_READ_ONLY_CONSUMER
```

Candidate stub: `scripts/research/patch2b1_paper_controller_candidate_stub.py` (forbids refresh/append; research-only writes).

---

## F. Auction Synthesis

```text
NONE_DIRECT
```

No read of `auction_synthesis_memory` / reinforcement paths. Stale `ACTIVE_BROKEN` auction_synthesis does **not** block paper via direct dependency.  
(`PATCH2B1_BLOCKED_BY_AUCTION_SYNTHESIS` does not apply.)

---

## G. Signal / Order / Fill

Artifact: `data/research/patch2b1_signal_audit.csv`  
Lineage: `data/research/patch2b1_paper_pipeline_lineage.csv`

Flow:

```text
decision → evaluate_flat_entry_gate → write_open_position_chain
  → signal → order → fill (snapshot/intrabar) → position
→ evaluate_exit_preview → write_close_position_chain
```

Fill notes:

- Prefers event/intrabar/live snapshot; forbids context-origin synthetic fill  
- Not classic next-bar open; cycle uses current snapshot  
- Fees: entry 2 bps, exit 5 bps; slip entry 3 / exit 3 (stop/forced 5)  
- Under hold mode, stop/take exits are suppressed  

Look-ahead S0 (future candle close for decision fill): **not proven** in this forensic pass.

---

## H. Position Model

**Single global open position** (`STOPPED_MULTI_OPEN` if >1).  

Not multi-context / multi-TF books — future S4 limitation, not repaired here.

---

## I. Exit Logic

Default: **hold until directional context end/flip/OBSERVE**.  

CHALLENGED while context remains directional → hold.  
Stop/take active only if hold mode disabled.  
Artifact: `data/research/patch2b1_exit_audit.csv`

---

## J. P&L Reconciliation

Artifacts:

- `data/research/patch2b1_pnl_reconciliation.csv`  
- `data/research/patch2b1_pnl_anomalies.json`

| Metric | Value |
| --- | --- |
| Closed positions checked | 7 |
| Exact match vs `closed_trade_economics` net | **0** |
| Accounting mismatches (S1) | **7** |
| Look-ahead S0 | **false** |

Root cause pattern for controller positions:

```text
ledger_realized ≈ gross − 10bps·notional
canonical_net   = gross − (2+5+3+3)bps·notional
```

≈ **exit slippage omitted** from ledger realized (~$3 on $10k notional).  
Small favorable moves can show negative ledger P&L due to cost drag (S2), not inverted price math.

---

## K. Sizing

Confirmed in `scripts/live/paper_trade_economics.py`:

| Parameter | Value |
| --- | --- |
| deposit / initial capital | **100000** USD |
| max_risk_pct | **1.0** |
| max_risk_usd | **1000** |
| sizing_method | `risk_based_stop_loss_cost_aware` |
| cost_aware_stop_sizing | true |
| fixed_notional_used | false (legacy 10k notional appears in some metadata only) |
| entry_fee | 0.02% (2 bps) |
| exit_fee | 0.05% (5 bps) |

---

## L. Candidate Comparison

Artifact: `data/research/patch2b1_candidate_comparison.json`  
Candidate parquets under `data/research/patch2b1_candidate_*.parquet` (annotated baseline copies; production untouched).

| Status | Meaning |
| --- | --- |
| Ledger copy | annotation-only candidate outputs |
| Logic | **LEGACY_DEFECT** (P&L accounting + hidden trigger + gate/hold drift) |
| UNEXPLAINED | none for copy identity |

---

## M. Tests

```bash
export BTC_ML_CONTINUATION_PROGRESSION=0 PRICE_GATE=OFF
venv/bin/python -m pytest \
  tests/test_patch2b1_paper_controller_forensics.py \
  tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py \
  tests/test_paper_trade_economics_contract.py \
  tests/test_runtime_dataset_metadata_patch1.py \
  tests/test_collector_watchdog_restart_contract.py \
  -q
```

**Result:** 79 passed, **2 failed** (known preview debt `test_04`, `test_08`).

---

## N. Safety

| Check | Status |
| --- | --- |
| Production paper controller | DEAD |
| Production paper sha/mtime | unchanged |
| Context daemon | not started by this patch |
| auction_synthesis repair | not done |
| belief→paper | not done |
| execution / exchange | unused |
| commit / push | not done |

---

## O. Next Step

```text
PATCH 2B.2 — PAPER CONTROLLER LOGIC REPAIR
```

Required before any live recovery:

1. Strip hidden context ownership → `PAPER_READ_ONLY_CONSUMER` (`skip_refresh` default)  
2. Fix / isolate `context_entered_at` decision schema defect (upstream)  
3. Decide exit canon: hold-until-context-end **vs** stop-first; align tests to canon  
4. Align ledger realized P&L with `closed_trade_economics`  
5. Only then: `PATCH 2B.2 — PAPER CONTROLLER LIVE RECOVERY` (if gates pass)

---

## Artifacts index

| Path | Role |
| --- | --- |
| `data/research/patch2b1_preflight_20260724_143505.json` | Preflight |
| `data/research/patch2b1_processes_20260724_143505.json` | Process snapshot |
| `data/research/patch2b1_paper_pipeline_lineage.csv` | Pipeline map |
| `data/research/patch2b1_preview_test_failures.json` | Preview RCA |
| `data/research/patch2b1_decision_to_paper_contract.json` | Input contract |
| `data/research/patch2b1_signal_audit.csv` | Signals |
| `data/research/patch2b1_exit_audit.csv` | Exits |
| `data/research/patch2b1_pnl_reconciliation.csv` | P&L recompute |
| `data/research/patch2b1_pnl_anomalies.json` | Anomalies |
| `data/research/patch2b1_candidate_comparison.json` | OLD vs candidate |
| `data/research/patch2b1_candidate_paper_*.parquet` | Candidate outputs |
| `scripts/research/patch2b1_paper_controller_candidate_stub.py` | Candidate constraints |
| `tests/test_patch2b1_paper_controller_forensics.py` | Forensic tests |
