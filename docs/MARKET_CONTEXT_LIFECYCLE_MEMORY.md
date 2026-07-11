# Market Context Lifecycle Memory

Shadow lifecycle layer over choppy per-bar `final_market_context_memory`.

## Why this layer exists

`final_market_context_memory` is a **per-bar market interpretation**.
It can flip LONG/SHORT/OBSERVE almost every bar.

A chart needs a **lifecycle**:

- candidate
- active context
- challenged context
- invalidated / no active context

This layer publishes:

1. `market_context_lifecycle_memory.parquet` — bar-level lifecycle state
2. `market_context_lifecycle_episodes.parquet` — intervals of `active_market_context`

## Raw vs active

| Field | Meaning |
|---|---|
| `raw_market_context` | Bar interpretation from final_market_context_memory |
| `active_market_context` | Stable context the chart should paint |

`DEVELOPING` raw directional context can become a **candidate**, but cannot instantly become active.
`OBSERVE` can **challenge** an active directional context, but does not instantly end it.
Only a confirmed opposite `ACTIVE` context (or `INVALIDATED`) replaces / clears the active context.

## Why no manual TTL

No “N bars then expire”.
No rolling-window smoothing.
No rewriting history from later price.

Lifetime ends only when:

- confirmed opposite context becomes active, or
- source row is `INVALIDATED`

`active_context_age_bars` is diagnostic only.

## Why DEVELOPING cannot flip active context

`DEVELOPING` means the bar reading is not confirmed.
Allowing it to flip active LONG ↔ SHORT recreates the choppy chart problem.

So:

- OBSERVE + DEVELOPING LONG → `CANDIDATE`, active stays OBSERVE
- ACTIVE LONG + DEVELOPING SHORT → `CHALLENGED`, active stays LONG
- ACTIVE LONG + ACTIVE SHORT → active becomes SHORT

## Why OBSERVE challenges instead of always ending

OBSERVE often means “no clear directional reading on this bar”, not “the prior process is dead”.
Ending active context on every OBSERVE bar would shatter episodes again.

OBSERVE while LONG/SHORT is active → `CHALLENGED`.
A later confirmed opposite ACTIVE context can replace it.

## action_allowed does not rewrite market context

`action_allowed` / `action_reason` are carried through for diagnostics.
They never change `active_market_context`.
Trade policy must not erase market truth.

## Chart should read lifecycle episodes

Paint intervals from `market_context_lifecycle_episodes.parquet` using `active_market_context`.

Do **not** paint raw per-bar flips from `final_market_context_episodes.parquet` as the primary visual.

CHALLENGED bars stay inside the same active episode until `active_market_context` actually changes.

## Shadow-only

- `shadow_only=True`
- not in `CANONICAL_PIPELINE`
- not execution

## How to run

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_lifecycle_memory.py
```

Tests:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_market_context_lifecycle_memory.py -q
```
