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
Auction neutralization or a **persistent** confirmed opposite `ACTIVE` context closes / replaces it.
A single confirmed opposite bar does **not** replace.

## CHALLENGED is not terminal

`CHALLENGED` means the active directional thesis is contested, not dead.

It stays challenged when:

- raw OBSERVE appears without full auction/cognitive BALANCE confluence
- opposite DEVELOPING appears (DEVELOPING never replaces an active context)
- a single confirmed opposite `ACTIVE` bar appears without persistence
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

A neutralization confluence bar for an active SHORT or LONG requires **all** of:

- `raw_market_context == OBSERVE`
- `raw_context_status == OBSERVE`
- `raw_cognitive_market_state == BALANCE`
- `raw_state_direction == NEUTRAL`
- `auction_episode == BALANCE`

### Termination persistence protection

A single neutralization confluence bar must **not** kill a confirmed active context.
A single confirmed opposite `ACTIVE` bar must **not** kill it either.
Three conservative persistence rules protect directional episodes (shadow-only; no execution):

- `NEUTRALIZATION_CONFIRM_BARS = 2` — a confirmed context is invalidated only after
  this many **consecutive** neutralization confluence bars. The first confluence bar
  sets `lifecycle_state = CHALLENGED` while keeping the existing LONG/SHORT active.
- `MIN_ACTIVE_CONTEXT_HOLD_BARS = 3` — a fresh context whose
  `active_context_age_bars < MIN_ACTIVE_CONTEXT_HOLD_BARS` is never invalidated by
  auction neutralization, a source `INVALIDATED` row, **or** confirmed opposite
  replacement. It is held as `CHALLENGED` with the active context unchanged until
  the minimum hold is met.
- `CONFIRMED_OPPOSITE_CONFIRM_BARS = 2` — opposite `ACTIVE` replaces the living
  thesis only after this many **consecutive** confirmed opposite bars on a mature
  context. The first opposite `ACTIVE` bar sets `CHALLENGED` and keeps the
  previous LONG/SHORT. This is the same persistence family as neutralization:
  it delays termination; it is not a trading signal and does not force a reversal.

There is **no exemption** for opposite CONFIRMED replacement. The historical
“replace immediately on one opposite ACTIVE bar” hole is closed.

`invalidation_type` describes the exact event row only. It is **not** carried forward
onto later `NO_ACTIVE_CONTEXT` / `CANDIDATE` rows.

This is a persistence/debounce rule only. No `challenge_ratio` rule. No price rewrite.

## Why no manual TTL

No “N bars then expire” (there is no expiry — an undisturbed active context lives on).
No rolling-window smoothing.
No rewriting history from later price.
The only N-bar element is the neutralization / opposite-confirm / hold
**persistence** debounce above, which delays termination; it never forces one.

Episode ends when:

- auction/cognitive neutralization invalidates active context, or
- persistent confirmed opposite context becomes active, or
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
- ACTIVE LONG + one ACTIVE SHORT → `CHALLENGED`, active stays LONG
- ACTIVE LONG + two consecutive ACTIVE SHORT (mature hold) → active becomes SHORT (`OPPOSITE_CONTEXT_REPLACEMENT`)

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
