# Market Context Demo Pack

## 1. Current status

- latest active context: `OBSERVE`
- lifecycle state: `NO_ACTIVE_CONTEXT`
- active directional context age: `0` (no active directional context)
- previous active context: `LONG_CONTEXT` (AUCTION_NEUTRALIZATION)
- action allowed: `False`
- chain status: `PASS`
- demo pack status: `PASS`

## 2. What the graph shows

- green fill = active `LONG_CONTEXT`
- red fill = active `SHORT_CONTEXT`
- faded / hatched fill = `CHALLENGED` active context
- no fill = `OBSERVE`
- this is **not** a trade signal; execution remains disabled

## 3. Latest context explanation

- active_market_context: `OBSERVE`
- lifecycle_state: `NO_ACTIVE_CONTEXT`
- challenge_ratio: `0.0`
- action_allowed: `False`

No active directional context. Previous active context LONG_CONTEXT was cancelled via AUCTION_NEUTRALIZATION. LONG_CONTEXT invalidated because auction and cognitive state moved to BALANCE / NEUTRAL / OBSERVE; no confirmed opposite context required. This is not a new opposite LONG/SHORT context. action_allowed=False because shadow market context only; execution disabled.

## 4. Last 20 context episodes

| episode_id | context | start | end | bars | challenged | explanation |
|---|---|---|---|---|---|---|
| 405 | OBSERVE | 2026-07-09T09:15:00Z | 2026-07-09T09:30:00Z | 2 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 406 | LONG_CONTEXT | 2026-07-09T09:45:00Z | 2026-07-09T10:00:00Z | 2 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 407 | SHORT_CONTEXT | 2026-07-09T10:15:00Z | 2026-07-09T10:15:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was ACCEPTANCE_LOWER, derived from auction episode ACCEPTANCE_LOWER showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 408 | LONG_CONTEXT | 2026-07-09T10:30:00Z | 2026-07-10T01:45:00Z | 23 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 409 | SHORT_CONTEXT | 2026-07-10T02:15:00Z | 2026-07-10T07:00:00Z | 13 | 4 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 410 | OBSERVE | 2026-07-10T07:15:00Z | 2026-07-10T09:00:00Z | 8 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 411 | SHORT_CONTEXT | 2026-07-10T09:15:00Z | 2026-07-10T10:15:00Z | 5 | 1 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed directional context became active. |
| 412 | OBSERVE | 2026-07-10T10:30:00Z | 2026-07-12T00:15:00Z | 152 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 413 | LONG_CONTEXT | 2026-07-12T00:30:00Z | 2026-07-12T01:30:00Z | 5 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 414 | OBSERVE | 2026-07-12T01:45:00Z | 2026-07-12T05:45:00Z | 17 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 415 | LONG_CONTEXT | 2026-07-12T06:00:00Z | 2026-07-12T07:00:00Z | 5 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 416 | OBSERVE | 2026-07-12T07:15:00Z | 2026-07-12T09:00:00Z | 8 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 417 | LONG_CONTEXT | 2026-07-12T09:15:00Z | 2026-07-12T09:15:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 418 | OBSERVE | 2026-07-12T09:30:00Z | 2026-07-12T09:30:00Z | 1 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. Episode ended because source context was invalidated. |
| 419 | LONG_CONTEXT | 2026-07-12T09:45:00Z | 2026-07-12T10:00:00Z | 2 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 420 | OBSERVE | 2026-07-12T10:15:00Z | 2026-07-12T21:45:00Z | 47 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 421 | LONG_CONTEXT | 2026-07-12T22:00:00Z | 2026-07-12T23:00:00Z | 5 | 1 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 422 | OBSERVE | 2026-07-12T23:15:00Z | 2026-07-13T01:15:00Z | 9 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 423 | LONG_CONTEXT | 2026-07-13T01:30:00Z | 2026-07-13T02:00:00Z | 3 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 424 | OBSERVE | 2026-07-13T02:15:00Z | 2026-07-13T05:45:00Z | 15 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |

## 5. Source trace

| episode_id | auction_episode | cognitive_market_state | market_context | lifecycle_state |
|---|---|---|---|---|
| 405 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 406 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 407 | ACCEPTANCE_LOWER | ACCEPTANCE_LOWER | SHORT_CONTEXT | ACTIVE |
| 408 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 409 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 410 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 411 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 412 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 413 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 414 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 415 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 416 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 417 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 418 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 419 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 420 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 421 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 422 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 423 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 424 | BALANCE | BALANCE | OBSERVE | INVALIDATED |

## 6. Acceptance checks

| check | result |
|---|---|
| `chain_status_is_pass` | `PASS` |
| `lifecycle_episodes_less_than_raw` | `PASS` |
| `no_failed_short_reprice` | `PASS` |
| `no_raw_chosen_context_in_visual` | `PASS` |
| `no_calibrated_context_in_visual` | `PASS` |
| `action_allowed_false` | `PASS` |
| `latest_context_available` | `PASS` |
| `latest_episode_open` | `PASS` |
| `visual_source_is_lifecycle` | `PASS` |

Overall: **PASS**

## Chain health

- memory rows: `5697`
- raw episodes: `1469`
- lifecycle episodes: `424`
- reduction ratio: `0.7114`
- forbidden labels found: `False`
- execution disabled: `True`
