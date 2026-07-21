# Bounded Paper Trading Controller (Auto Ledger / No Real Execution)

Approved bounded PAPER-ONLY controller that, on a fixed interval:

1. Runs safety preflight (`execution_enabled=false`, no exchange imports, max one open position)
2. Optionally refreshes live context and appends one decision-log row when a new closed context exists
3. If a paper position is OPEN: monitors stop / take / context-exit and may auto-close
4. If FLAT: evaluates directional entry and may auto-write signal → order → trade → position → equity
5. Appends controller cycle + action dataset rows for paper trading research

## Approval

Phrase:

`APPROVE_BOUNDED_PAPER_TRADING_CONTROLLER_AUTO_LEDGER_NO_REAL_EXECUTION`

Required flags:

```bash
--approved-bounded-paper-controller-auto-ledger \
--paper-only \
--no-real-execution
```

## Bounds

- `max_cycles = 96`
- `interval_seconds = 900` (15 minutes)
- `max_duration_hours = 24`
- stops on error / execution enabled / exchange detection / >1 open position

## Makefile

```bash
make bounded-paper-controller-auto-ledger-start
make bounded-paper-controller-auto-ledger-status
make bounded-paper-controller-auto-ledger-tail
make bounded-paper-controller-auto-ledger-stop
```

## Safety

- Real execution: forbidden
- Exchange API: forbidden
- Dashboard/server: not started
- Retraining / model fit: forbidden
- Max one open paper position
- Synthetic entry price `100000` forbidden
- Uses live close / stop-take levels only

## Outputs

Under `data/research/paper_simulator/`:

- `bounded_paper_controller_status.json`
- `bounded_paper_controller_state.json`
- `bounded_paper_controller_cycles.parquet` / `.csv`
- `bounded_paper_controller_actions.parquet` / `.csv`
- `bounded_paper_controller_safety.json`
- `bounded_paper_controller_final_decision.json`

Process:

- `logs/bounded_paper_trading_controller_auto_ledger.log`
- `run/bounded_paper_trading_controller_auto_ledger.pid`
