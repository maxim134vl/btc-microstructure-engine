# S4.1 ↔ LIVE1B Hybrid Execution

Status: **HYBRID (production intent)**  
Date: 2026-08-15

## Goal

```text
MTF / lifecycle
  → S4.1 TimeframeManager → timeframe_command_memory.parquet
                              ↓
                    LIVE1B IntrabarPaperEngine
                              ↓
              paper epoch books / sleeves / 400k capital / PnL
```

- **Manager:** S4.1 (independent TF commands)
- **Execution / books / capital:** LIVE1B epoch (`PER_TF_EQUITY_*`)
- **S4.1 TimeframeTrader processes:** STOPPED (no dual writers)
- **Context journal:** observe-only (no CONTEXT_START/FLIP fills)

## Config

`config/intrabar_paper_execution.json`:

- `entry_source`: `s41_command_bus`
- `s41_consume_commands_after`: UTC boundary (commands before are ignored). On first LIVE1B cursor create, the paper manager raises this floor to now so void command-bus history is not replayed onto a live journal position.

`data/trading/manager/activation.json`:

- `execution_owner`: `LIVE1B_INTRABAR_PAPER`
- `hybrid.position_source`: `live1b_epoch_books`

## Cutover

```bash
venv/bin/python scripts/ops/s41_live1b_hybrid_cutover.py --execute
```

## Gates

1. No S4.1 trader PIDs writing books
2. LIVE1B paper manager alive + `active.json` ACTIVE
3. Manager portfolio views show LIVE1B opens (or flat) with continuous equity
4. New OPEN/CLOSE fills carry `manager_command_id` + LIVE1B BBO
5. Mid-context episodes already in `manager_state.traded_episode_ids` / `last_entry_episode_id` do not re-open. Opposite-episode FLIP still emits CLOSE then OPEN in the same cycle.
