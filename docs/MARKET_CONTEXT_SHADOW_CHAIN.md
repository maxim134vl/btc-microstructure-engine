# Market Context Shadow Chain

Reproducible **shadow-only** rebuild of the restored market-context stack.

This is **not** pipeline integration, **not** execution, and **not** a trade signal.

## Why a shadow chain

Stages 1–6 restored cognition layers as research builders outside `CANONICAL_PIPELINE`.
This script runs them in order so a full rebuild is one command.

## Layer order

1. `auction_episode_memory` — auction process episodes from bars/volume
2. `cognitive_market_state_memory` — cognitive market state from auction episodes
3. `final_market_context_memory` — per-bar LONG/SHORT/OBSERVE interpretation
4. `market_context_lifecycle_memory` + `market_context_lifecycle_episodes` — stable active context lifecycle
5. sandbox lifecycle visual JSON — Clean View chart inputs

## Why not execution

Every layer is diagnostic / observational.
`action_allowed` stays `False`.
`shadow_only=True`.
No orders, no runtime wiring, no collector changes.

## Why not in CANONICAL_PIPELINE

The restored chain is still being validated visually and forensically.
Putting it into `CANONICAL_PIPELINE` / `engine_registry` / `runtime_dependency_map` would change live runtime behavior.
That is intentionally deferred.

## How to run a full rebuild

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_shadow_chain.py
```

PASS writes:

- all cognition parquet artifacts above
- sandbox `lifecycle_*.json`
- `data/cognition/market_context_shadow_chain_status.json`

## How to run the sandbox

```bash
cd /Users/fontecrypto/btc-ml/sandbox/market_state_context_visualizer/public
python3 -m http.server 8765
```

Open: http://127.0.0.1:8765/

## Chart source of truth

Clean View reads **only**:

- `sandbox/.../lifecycle_candles.json`
- `sandbox/.../lifecycle_context_episodes.json`
- `sandbox/.../lifecycle_latest.json`

Those are generated from:

- `data/cognition/market_context_lifecycle_memory.parquet`
- `data/cognition/market_context_lifecycle_episodes.parquet`
- `data/live/live_market_feed.parquet`

Not from trading_state, market_state, arbitration, V4, or `FAILED_SHORT_REPRICE`.

## What counts as PASS

- every step exits 0
- every listed artifact exists with `rows > 0`
- latest timestamp present on each artifact
- `shadow_only=True` where the field exists
- final memory latest timestamp matches or is not older than lifecycle memory
- `lifecycle_latest.json` matches lifecycle memory latest
  (`active_market_context`, `lifecycle_state`, `active_context_age_bars`, `action_allowed`)
- lifecycle episode count < raw final-context episode count
- `action_allowed` remains False in new shadow layers
- no `FAILED_SHORT_REPRICE` in new outputs
- no `raw_chosen_context` / `calibrated_context` in lifecycle visual JSON

## Tests

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_market_context_shadow_chain.py -q
```
