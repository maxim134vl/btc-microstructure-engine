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
`OBSERVE` from `UNCERTAIN` / missing auction evidence is **not** a context: keep the living thesis.
`OBSERVE` with full BALANCE confluence can **challenge** an active directional context, but does not instantly end it.
Auction neutralization still needs two consecutive confluence bars.
A confirmed opposite `ACTIVE` bar **ends the living thesis to OBSERVE**. It must
**not** paint `LONG→SHORT` / `SHORT→LONG` on the same bar. The opposite may
become active only from OBSERVE on a later bar:
`LONG → OBSERVE → SHORT` (and reverse). Holding the old context for 3 M15 bars
(45 minutes) before that OBSERVE step was a live execution lag and is forbidden.

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

### Termination rules (S4.1 reads this — not shadow-only)

A single neutralization confluence bar must **not** kill a confirmed active context.
A confirmed opposite `ACTIVE` bar ends the living thesis **to OBSERVE**. Direct
`LONG→SHORT` / `SHORT→LONG` paint is forbidden. S4.1 HOLDs through OBSERVE and
only closes when the opposite becomes ACTIVE after that pause.

- `NEUTRALIZATION_CONFIRM_BARS = 2` — a confirmed context is invalidated only after
  this many **consecutive** neutralization confluence bars. The first confluence bar
  sets `lifecycle_state = CHALLENGED` while keeping the existing LONG/SHORT active.
  DEVELOPING same-direction or opposite bars **do not reset** this count. A
  `LOWER_ABSORPTION` developing print cannot resurrect a challenged LONG through
  BALANCE. Live ticks on the same TF bar count as one bar. S4.1 already HOLDs
  through OBSERVE, so this is chart flicker protection, not a trade delay.
- `MIN_ACTIVE_CONTEXT_HOLD_BARS = 0` — a fresh context may end to OBSERVE
  immediately. Do not restore `3` (45 minutes of M15).
- `CONFIRMED_OPPOSITE_CONFIRM_BARS = 1` — the first confirmed opposite `ACTIVE`
  bar ends the living thesis to OBSERVE (`OPPOSITE_CONTEXT_REPLACEMENT`). The
  opposite may become ACTIVE only from OBSERVE on a later bar. DEVELOPING
  opposite still only challenges.

`invalidation_type` describes the exact event row only. It is **not** carried forward
onto later `NO_ACTIVE_CONTEXT` / `CANDIDATE` rows.

This is not a trade-policy rewrite. No `challenge_ratio` rule. No price rewrite.

## Why no manual TTL

No “N bars then expire” (there is no expiry — an undisturbed active context lives on).
No rolling-window smoothing.
No rewriting history from later price.
The only remaining N-bar element is neutralization confirm (2 bars). There is
no minimum-age hold and no extra confirmed-opposite delay beyond the mandatory
OBSERVE bar between opposite directions.

Episode ends when:

- auction/cognitive neutralization invalidates active context, or
- confirmed opposite ACTIVE ends the living thesis to OBSERVE, or
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
- ACTIVE LONG + confirmed ACTIVE SHORT → active becomes OBSERVE (`OPPOSITE_CONTEXT_REPLACEMENT`); next confirmed SHORT from OBSERVE becomes SHORT

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

## Chart vs execution

S4.1 / live trading reads `active_market_context`. Chart bands should too.
`shadow_only=True` on the parquet rows is historical: it does **not** mean the
manager ignores this layer. Delaying replacement here delays OPEN and CLOSE.

- `shadow_only=True` remains on the builder output schema
- do not restore `MIN_ACTIVE_CONTEXT_HOLD_BARS = 3` (45 minutes of M15)

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
