# Market Context Demo Pack

## 1. Current status

- latest active context: `OBSERVE`
- lifecycle state: `NO_ACTIVE_CONTEXT`
- active directional context age: `0` (no active directional context)
- previous active context: `SHORT_CONTEXT` (AUCTION_NEUTRALIZATION)
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

No active directional context. Previous active context SHORT_CONTEXT was cancelled via AUCTION_NEUTRALIZATION. SHORT_CONTEXT invalidated because auction and cognitive state moved to BALANCE / NEUTRAL / OBSERVE; no confirmed opposite context required. This is not a new opposite LONG/SHORT context. action_allowed=False because shadow market context only; execution disabled.

## 4. Last 20 context episodes

| episode_id | context | start | end | bars | challenged | explanation |
|---|---|---|---|---|---|---|
| 393 | OBSERVE | 2026-07-08T14:00:00Z | 2026-07-08T14:00:00Z | 1 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. Episode ended because source context was invalidated. |
| 394 | LONG_CONTEXT | 2026-07-08T14:15:00Z | 2026-07-08T14:15:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 395 | OBSERVE | 2026-07-08T14:30:00Z | 2026-07-08T14:30:00Z | 1 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. Episode ended because source context was invalidated. |
| 396 | LONG_CONTEXT | 2026-07-08T14:45:00Z | 2026-07-08T17:30:00Z | 12 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 397 | OBSERVE | 2026-07-08T17:45:00Z | 2026-07-08T19:15:00Z | 7 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 398 | LONG_CONTEXT | 2026-07-08T19:30:00Z | 2026-07-08T20:15:00Z | 4 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 399 | OBSERVE | 2026-07-08T20:30:00Z | 2026-07-09T03:00:00Z | 27 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 400 | LONG_CONTEXT | 2026-07-09T03:15:00Z | 2026-07-09T04:00:00Z | 4 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 401 | OBSERVE | 2026-07-09T04:15:00Z | 2026-07-09T04:45:00Z | 3 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 402 | LONG_CONTEXT | 2026-07-09T05:00:00Z | 2026-07-09T07:15:00Z | 10 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 403 | OBSERVE | 2026-07-09T07:30:00Z | 2026-07-09T07:30:00Z | 1 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. Episode ended because source context was invalidated. |
| 404 | LONG_CONTEXT | 2026-07-09T07:45:00Z | 2026-07-09T09:00:00Z | 6 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 405 | OBSERVE | 2026-07-09T09:15:00Z | 2026-07-09T09:30:00Z | 2 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 406 | LONG_CONTEXT | 2026-07-09T09:45:00Z | 2026-07-09T10:00:00Z | 2 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed directional context became active. |
| 407 | SHORT_CONTEXT | 2026-07-09T10:15:00Z | 2026-07-09T10:15:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was ACCEPTANCE_LOWER, derived from auction episode ACCEPTANCE_LOWER showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 408 | LONG_CONTEXT | 2026-07-09T10:30:00Z | 2026-07-10T01:45:00Z | 23 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 409 | SHORT_CONTEXT | 2026-07-10T02:15:00Z | 2026-07-10T07:00:00Z | 13 | 4 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 410 | OBSERVE | 2026-07-10T07:15:00Z | 2026-07-10T09:00:00Z | 8 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |
| 411 | SHORT_CONTEXT | 2026-07-10T09:15:00Z | 2026-07-10T10:15:00Z | 5 | 1 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed directional context became active. |
| 412 | OBSERVE | 2026-07-10T10:30:00Z | 2026-07-11T07:00:00Z | 83 | 0 | OBSERVE because cognitive state was BALANCE, derived from auction episode BALANCE. No confirmed directional context is active. |

## 5. Source trace

| episode_id | auction_episode | cognitive_market_state | market_context | lifecycle_state |
|---|---|---|---|---|
| 393 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 394 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 395 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 396 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 397 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 398 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 399 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 400 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 401 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 402 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 403 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 404 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 405 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 406 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 407 | ACCEPTANCE_LOWER | ACCEPTANCE_LOWER | SHORT_CONTEXT | ACTIVE |
| 408 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 409 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 410 | BALANCE | BALANCE | OBSERVE | INVALIDATED |
| 411 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 412 | BALANCE | BALANCE | OBSERVE | INVALIDATED |

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

- memory rows: `5510`
- raw episodes: `1418`
- lifecycle episodes: `412`
- reduction ratio: `0.7094`
- forbidden labels found: `False`
- execution disabled: `True`
