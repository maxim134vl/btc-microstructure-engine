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
`OBSERVE` alone can **challenge** an active directional context, but does not instantly end it.
Auction neutralization or a confirmed opposite `ACTIVE` context closes / replaces it.

## CHALLENGED is not terminal

`CHALLENGED` means the active directional thesis is contested, not dead.

It stays challenged when:

- raw OBSERVE appears without full auction/cognitive BALANCE confluence
- opposite DEVELOPING appears without confirmed ACTIVE replacement
- evidence is incomplete

It must **not** hang forever once auction neutralization arrives.

## INVALIDATED closes old directional context

`INVALIDATED` closes the previous LONG/SHORT and sets:

- `active_market_context = OBSERVE`
- `invalidation_type = AUCTION_NEUTRALIZATION` (or `OPPOSITE_CONTEXT_REPLACEMENT` / `THESIS_REJECTION`)
- `previous_active_market_context` = the closed context

BALANCE neutralization does **not** create a new LONG or SHORT.
After invalidation the system stays in OBSERVE until a confirmed directional context appears.

### Auction neutralization confluence

For active SHORT or LONG, invalidate only when **all** are true:

- `raw_market_context == OBSERVE`
- `raw_context_status == OBSERVE`
- `raw_cognitive_market_state == BALANCE`
- `raw_state_direction == NEUTRAL`
- `auction_episode == BALANCE`

No TTL. No N-bar rule. No `active_context_age_bars` rule. No `challenge_ratio` rule. No price rewrite.

## Why no manual TTL

No “N bars then expire”.
No rolling-window smoothing.
No rewriting history from later price.

Episode ends when:

- auction/cognitive neutralization invalidates active context, or
- confirmed opposite context becomes active, or
- source row is `INVALIDATED`

`active_context_age_bars` is diagnostic only and applies **only** while
`active_market_context` is LONG_CONTEXT or SHORT_CONTEXT.

If `active_market_context == OBSERVE` or `lifecycle_state` is
`NO_ACTIVE_CONTEXT` / `INVALIDATED`:

- `active_context_age_bars = 0`
- `active_context_started_at = null`

There is no active directional context to age.

## Why DEVELOPING cannot flip active context

`DEVELOPING` means the bar reading is not confirmed.
Allowing it to flip active LONG ↔ SHORT recreates the choppy chart problem.

So:

- OBSERVE + DEVELOPING LONG → `CANDIDATE`, active stays OBSERVE
- ACTIVE LONG + DEVELOPING SHORT → `CHALLENGED`, active stays LONG
- ACTIVE LONG + ACTIVE SHORT → active becomes SHORT (`OPPOSITE_CONTEXT_REPLACEMENT`)

## Why OBSERVE challenges instead of always ending

OBSERVE alone often means “no clear directional reading on this bar”, not “the prior process is dead”.
Ending active context on every OBSERVE bar would shatter episodes again.

OBSERVE while LONG/SHORT is active → `CHALLENGED`, unless full BALANCE neutralization confluence is present.

## Invalidation is not a trade signal

Closing SHORT/LONG to OBSERVE is observational.
`action_allowed` stays `False`.
No execution.

## Chart should read lifecycle episodes

Paint intervals from `market_context_lifecycle_episodes.parquet` using `active_market_context`.

Do **not** paint raw per-bar flips from `final_market_context_episodes.parquet` as the primary visual.

CHALLENGED bars stay inside the same active episode until `active_market_context` actually changes.
Auction neutralization ends the directional episode and starts an OBSERVE episode.

## Shadow-only

- `shadow_only=True`
- not in `CANONICAL_PIPELINE`
- not execution

## How to run

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_lifecycle_memory.py
```

Or full shadow chain:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_market_context_shadow_chain.py
```

Tests:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_market_context_lifecycle_memory.py -q
```
