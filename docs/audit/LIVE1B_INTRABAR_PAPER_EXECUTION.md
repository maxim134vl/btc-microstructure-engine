# LIVE1B — Intrabar paper execution (context events → causal BBO)

Status: `LIVE1B_INTRABAR_PAPER_TRADING_ACTIVE` (after cutover)

## Path

```text
intrabar context journal
  → ContextEventConsumer (durable checkpoint, idempotent keys)
  → IntrabarPaperEngine
  → causal BBO fill (LONG entry ask / SHORT entry bid; exits opposite)
  → TP/SL on market events; CONTEXT_END / CONTEXT_FLIP exits
  → epoch-isolated JSONL books
```

## Safety

- `paper_only = true`
- `real_execution_enabled = false`
- Legacy closed-bar manager/traders stopped and voided
- LIVE1A cognition service left running

## Config

`config/intrabar_paper_execution.json` — all fees, slippage, risk, and `max_bbo_age_ms` are explicit.

## Control

```bash
python scripts/live/live1b_cutover_activate.py
python scripts/live/intrabar_paper_ctl.py start|stop|status
```
