# PATCH 2B.2 — Paper Controller Logic Repair

**Tag:** `20260724_145726`  
**Branch:** `memory/canonical-system`  
**Basis:** `PAPER_CONTROLLER_REQUIRES_LOGIC_REPAIR` (Patch 2B.1)

---

## A. Result

```text
PAPER_CONTROLLER_REPAIR_CANDIDATE_READY
```

Production paper controller **not started**. Production paper parquet **unchanged**. Candidate gates pass (`UNEXPLAINED=0`, CTRL P&L matches canonical economics, preview failures=0).

---

## B. Proven Defects

Registry: `data/research/patch2b2_proven_defects.json`

| ID | Severity | Title | Repair |
| --- | --- | --- | --- |
| P2B2-D01 | S1_CONTROLLER_LOGIC | Hidden context trigger | Default `skip_refresh=True`; ctl always `--skip-refresh`; opt-in `--enable-context-refresh` only |
| P2B2-D02 | S1_CONTROLLER_LOGIC | Arrow crash on decision append | Avoided by D01 (paper no longer writes decision plane by default) |
| P2B2-D03 | S0_PNL_CORRUPTION | Ledger ≠ canonical net | Close path forces `fees_paid`/`slippage_paid` from `closed_trade_economics`; candidate restates CTRL positions |
| P2B2-D04 | S3_TEST_DRIFT | test_04 stop-first vs hold | Test updated to canonical hold default + `hold_mode=OFF` stop-first |
| P2B2-D05 | S3_TEST_DRIFT | test_08 missing episode key | Test asserts fail-closed incomplete fixture + allow with complete episode fields |
| P2B2-D06 | S0_FILL_OR_LOOKAHEAD | No fill timestamp guard | `_fill_after_decision_ok` requires `decision_ts < fill_ts` else `NO_FILL` |

Unresolved intent (not repaired): whether stop/take should ever override hold in production; ONE_SHOT fixture ledger quirks.

---

## C. Code Repairs

| File | Change |
| --- | --- |
| `scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py` | `DEFAULT_SKIP_REFRESH=True`, `PAPER_OWNERSHIP_CLASS=PAPER_READ_ONLY_CONSUMER`, fill guard, economics totals on close, argparse `--enable-context-refresh` |
| `scripts/bounded_paper_trading_controller_ctl.sh` | Always pass `--skip-refresh` |
| `tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py` | Preview tests aligned to canon |
| `scripts/research/patch2b2_paper_controller_candidate_replay.py` | Candidate restatement + restart sim |
| `tests/test_patch2b2_paper_controller_logic_repair.py` | Repair contract suite |

---

## D. Preview Tests

Both previously failing tests now **pass** under canonical meaning:

1. **test_04** — default hold → `PREVIEW_HOLD_LONG`; stop-first only with `hold_mode=OFF`  
2. **test_08** — incomplete fixture fail-closed; complete episode fixture allows; stale still blocks; synthetic price constant preserved  

---

## E. Fill Contract

```text
decision_timestamp < fill_timestamp
```

Else:

```text
NO_FILL / NO_FILL_FILL_NOT_AFTER_DECISION
```

Equal timestamps rejected (no same-bar close-as-fill). Synthetic `100000` price still forbidden.

---

## F. Position State

Granularity unchanged: **one global open position**.  
Candidate restart simulation: restatement idempotent (`restart_simulation_idempotent=true`).  
No multi-position architecture added.

---

## G. Exit Logic

No change to hold-until-context-end canon. Stop/take remain available only when `hold_mode=OFF`. Context flip still closes under hold.

---

## H. P&L

Candidate restatement of `PAPER_POSITION_CTRL_*`:

| Metric | Value |
| --- | --- |
| EXPECTED_DEFECT_FIX | 4 |
| UNCHANGED (ONE_SHOT etc.) | 3 |
| UNEXPLAINED | 0 |
| CTRL canonical matches | 4/4 |
| Sign mismatches | 0 |

Independent file: `data/research/patch2b2_pnl_reconciliation.csv`

---

## I. Sizing

Unchanged: deposit 100000 · max risk 1% / $1000 · `risk_based_stop_loss_cost_aware` · fees 2/5 bps · cost-aware stop sizing.

---

## J. Candidate Replay

Inputs: production paper ledgers (read-only).  
Outputs:

```text
data/research/patch2b2_candidate_paper_signals.parquet
data/research/patch2b2_candidate_paper_orders.parquet
data/research/patch2b2_candidate_paper_trades.parquet
data/research/patch2b2_candidate_positions.parquet
data/research/patch2b2_candidate_controller_state.json
data/research/patch2b2_old_vs_candidate.csv
data/research/patch2b2_candidate_summary.json
```

---

## K. Restart Simulation

Temp candidate dir re-restatement → identical economic columns; state file records `restart_simulation_idempotent=true`. Stale PID/lock unused as trading state.

---

## L. Tests

```bash
export BTC_ML_CONTINUATION_PROGRESSION=0 PRICE_GATE=OFF
venv/bin/python scripts/research/patch2b2_paper_controller_candidate_replay.py
venv/bin/python -m pytest \
  tests/test_patch2b2_paper_controller_logic_repair.py \
  tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py \
  tests/test_patch2b1_paper_controller_forensics.py \
  tests/test_paper_trade_economics_contract.py \
  tests/test_runtime_dataset_metadata_patch1.py \
  tests/test_collector_watchdog_restart_contract.py \
  -q
```

**Result:** 107 passed (plus ownership assertion updated for 2B.2 read-only default). Preview failures: **0**.

---

## M. Production Preservation

Preflight: `data/research/patch2b2_preflight_20260724_145726.json`  

Paper signals/orders/trades/positions: **sha256 and mtime unchanged**.

---

## N. Safety

| Check | Status |
| --- | --- |
| Production controller start | no |
| Production paper writes | 0 |
| Context/lifecycle/decision writes by paper default | no |
| Exchange | unused |
| CONTINUATION / PRICE_GATE | 0 / OFF |
| Commit / push | not done |

---

## O. Next Step

```text
PATCH 2B.3 — PAPER CONTROLLER SAFE PRODUCTION ACTIVATION
```

Only after explicit activation gates: single writer, skip-refresh enforced live, optional historical CTRL P&L restatement approval, and no decision-plane writes.
