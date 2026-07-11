# Cognitive Market State Memory

Shadow interpretation layer after `auction_episode_memory` and before a future
`final_market_context_memory`.

## Why this layer exists

`auction_episode_memory` answers: **what auction episode is observed on this bar?**

`cognitive_market_state_memory` answers: **what market process does that episode imply?**

Examples:

- episode `UPPER_DISTRIBUTION` → cognitive state `UPPER_DISTRIBUTION` with direction `SELLER_PRESSURE`
- episode `LOWER_ABSORPTION` → cognitive state `LOWER_ABSORPTION` with direction `BUYER_SUPPORT`
- episode `BALANCE` → cognitive state `BALANCE` with direction `NEUTRAL`

This restores a missing middle vocabulary between raw auction observations and
final directional context.

## Auction episode vs cognitive market state

| Layer | Question | Examples |
|---|---|---|
| `auction_episode` | What auction pattern is present? | `FAILED_BREAKOUT`, `CONTINUATION`, `BALANCE` |
| `cognitive_market_state` | How should that pattern be read as market process? | `UPPER_DISTRIBUTION`, `BUYER_CONTROL`, `UNCERTAIN` |

Some labels intentionally overlap (`UPPER_DISTRIBUTION`, `BALANCE`) when the episode
already is the process interpretation. Others are remapped
(`FAILED_BREAKOUT` → `UPPER_DISTRIBUTION`, `CONTINUATION`+buyer → `BUYER_CONTROL`).

## Bar events are not cognitive states

These remain **events / effort observations**, not cognitive market states:

- `BUYING_CLIMAX`
- `SELLING_CLIMAX`
- `STOPPING_VOLUME`
- `ABSORPTION_RESPONSE`

They may help form an auction episode upstream. This layer never promotes them
directly into `cognitive_market_state`.

## No LONG_CONTEXT / SHORT_CONTEXT

This builder never writes:

- `LONG_CONTEXT`
- `SHORT_CONTEXT`

Those belong to a later final-context / arbitration surface. Cognitive market
state uses process language (`SELLER_PRESSURE`, `BUYER_SUPPORT`, `NEUTRAL`, …).

## No hand-coded state lifetime

`state_status` mirrors the primary episode status (`DEVELOPING` / `CONFIRMED` /
`INVALIDATED` / `UNKNOWN`).

This stage does **not** say a state “lives N bars”. Duration will later be derived
from runs of identical `cognitive_market_state` values over time.

## Path to final market context (later)

Future `final_market_context_memory` can consume sequences of cognitive states to decide:

- whether process pressure is actionable as research context
- when to stay `OBSERVE`
- when a directional research context is justified

That final layer is out of scope here. This stage only publishes the cognitive
process reading, `shadow_only=True`, outside `CANONICAL_PIPELINE`.

## How to run

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_cognitive_market_state_memory.py
```

Requires:

```bash
venv/bin/python scripts/research/build_auction_episode_memory.py
```

Tests:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_cognitive_market_state_memory.py -q
```

Output: `data/cognition/cognitive_market_state_memory.parquet`
