# Market Context Demo Pack

## 1. Current status

- latest active context: `SHORT_CONTEXT`
- lifecycle state: `CHALLENGED`
- age: `59` bars
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

- active_market_context: `SHORT_CONTEXT`
- lifecycle_state: `CHALLENGED`
- challenge_ratio: `0.7833`
- action_allowed: `False`

SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. Episode is challenged because recent raw context is OBSERVE, but no confirmed opposite context replaced it. Current age is 59 bars; challenge_ratio=0.7833. action_allowed=False because shadow market context only; execution disabled.

## 4. Last 20 context episodes

| episode_id | context | start | end | bars | challenged | explanation |
|---|---|---|---|---|---|---|
| 154 | LONG_CONTEXT | 2026-07-07T06:15:00Z | 2026-07-07T06:15:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 155 | SHORT_CONTEXT | 2026-07-07T06:30:00Z | 2026-07-07T11:15:00Z | 20 | 1 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 156 | LONG_CONTEXT | 2026-07-07T11:30:00Z | 2026-07-07T11:45:00Z | 2 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 157 | SHORT_CONTEXT | 2026-07-07T12:00:00Z | 2026-07-07T14:00:00Z | 9 | 0 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 158 | LONG_CONTEXT | 2026-07-07T14:15:00Z | 2026-07-07T14:15:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 159 | SHORT_CONTEXT | 2026-07-07T14:30:00Z | 2026-07-07T14:30:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 160 | LONG_CONTEXT | 2026-07-07T14:45:00Z | 2026-07-07T14:45:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 161 | SHORT_CONTEXT | 2026-07-07T15:00:00Z | 2026-07-07T15:00:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 162 | LONG_CONTEXT | 2026-07-07T15:15:00Z | 2026-07-07T15:45:00Z | 3 | 2 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. Episode is challenged because recent raw context is OBSERVE, but no confirmed opposite context replaced it. |
| 163 | SHORT_CONTEXT | 2026-07-07T16:00:00Z | 2026-07-07T19:00:00Z | 13 | 1 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 164 | LONG_CONTEXT | 2026-07-07T19:15:00Z | 2026-07-07T19:15:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 165 | SHORT_CONTEXT | 2026-07-07T19:30:00Z | 2026-07-07T23:45:00Z | 18 | 0 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 166 | LONG_CONTEXT | 2026-07-08T00:00:00Z | 2026-07-08T00:00:00Z | 1 | 0 | LONG_CONTEXT because cognitive state was ACCEPTANCE_HIGHER, derived from auction episode ACCEPTANCE_HIGHER showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 167 | SHORT_CONTEXT | 2026-07-08T00:15:00Z | 2026-07-08T01:45:00Z | 7 | 0 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 168 | LONG_CONTEXT | 2026-07-08T02:00:00Z | 2026-07-08T03:15:00Z | 6 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 169 | SHORT_CONTEXT | 2026-07-08T03:30:00Z | 2026-07-08T03:30:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was ACCEPTANCE_LOWER, derived from auction episode ACCEPTANCE_LOWER showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 170 | LONG_CONTEXT | 2026-07-08T03:45:00Z | 2026-07-09T10:00:00Z | 122 | 51 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 171 | SHORT_CONTEXT | 2026-07-09T10:15:00Z | 2026-07-09T10:15:00Z | 1 | 0 | SHORT_CONTEXT because cognitive state was ACCEPTANCE_LOWER, derived from auction episode ACCEPTANCE_LOWER showing seller pressure. Activated via: confirmed opposite context replaced active context. |
| 172 | LONG_CONTEXT | 2026-07-09T10:30:00Z | 2026-07-10T01:45:00Z | 23 | 0 | LONG_CONTEXT because cognitive state was LOWER_ABSORPTION, derived from auction episode LOWER_ABSORPTION showing buyer-side pressure. Activated via: confirmed opposite context replaced active context. |
| 173 | SHORT_CONTEXT | 2026-07-10T02:15:00Z | 2026-07-10T18:45:00Z | 60 | 47 | SHORT_CONTEXT because cognitive state was UPPER_DISTRIBUTION, derived from auction episode UPPER_DISTRIBUTION showing seller pressure. Activated via: confirmed opposite context replaced active context. Episode is challenged because recent raw context is OBSERVE, but no confirmed opposite context replaced it. |

## 5. Source trace

| episode_id | auction_episode | cognitive_market_state | market_context | lifecycle_state |
|---|---|---|---|---|
| 154 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 155 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 156 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 157 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 158 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 159 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 160 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 161 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 162 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 163 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 164 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 165 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 166 | ACCEPTANCE_HIGHER | ACCEPTANCE_HIGHER | LONG_CONTEXT | ACTIVE |
| 167 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |
| 168 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 169 | ACCEPTANCE_LOWER | ACCEPTANCE_LOWER | SHORT_CONTEXT | ACTIVE |
| 170 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 171 | ACCEPTANCE_LOWER | ACCEPTANCE_LOWER | SHORT_CONTEXT | ACTIVE |
| 172 | LOWER_ABSORPTION | LOWER_ABSORPTION | LONG_CONTEXT | ACTIVE |
| 173 | UPPER_DISTRIBUTION | UPPER_DISTRIBUTION | SHORT_CONTEXT | ACTIVE |

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

- memory rows: `5461`
- raw episodes: `1409`
- lifecycle episodes: `173`
- reduction ratio: `0.8772`
- forbidden labels found: `False`
- execution disabled: `True`
