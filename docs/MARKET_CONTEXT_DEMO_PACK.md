# Market Context Demo Pack

Explainability and acceptance report for the restored market-context **shadow chain**.

This pack does **not** change model logic, visualizer, pipeline, arbitration, or execution.
It only reads shadow artifacts and writes a human-readable acceptance bundle.

## Purpose

Show, for each recent active context episode:

- why it is LONG / SHORT / OBSERVE
- which auction episode underlies it
- which cognitive state produced it
- where the episode started / ended
- why it is challenged (if CHALLENGED)
- which sources are fresh / unknown

## Inputs

- `data/cognition/auction_episode_memory.parquet`
- `data/cognition/cognitive_market_state_memory.parquet`
- `data/cognition/final_market_context_memory.parquet`
- `data/cognition/market_context_lifecycle_memory.parquet`
- `data/cognition/market_context_lifecycle_episodes.parquet`
- `data/cognition/market_context_shadow_chain_status.json`

Also checks sandbox visual JSON under:

- `apps/context_visualizer/public/data/lifecycle_*.json`

## Outputs

- `data/cognition/market_context_demo_pack.json`
- `docs/MARKET_CONTEXT_DEMO_PACK_OUTPUT.md`

## How to run

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_demo_pack.py
```

Recommended after a full shadow rebuild:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_shadow_chain.py
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_demo_pack.py
```

## What PASS means

All acceptance checks true:

- shadow chain status is PASS
- lifecycle episodes < raw episodes
- no `FAILED_SHORT_REPRICE`
- no `raw_chosen_context` / `calibrated_context` in visual JSON
- `action_allowed` remains False
- latest context available
- latest lifecycle episode is open
- visual source files are lifecycle outputs

When latest lifecycle is `INVALIDATED`, the demo explanation must include:

- which `previous_active_market_context` was closed
- `invalidation_reason` / `invalidation_type`
- that this is not a new opposite directional context
- that `action_allowed=False`

## Tests

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_market_context_demo_pack.py -q
```
