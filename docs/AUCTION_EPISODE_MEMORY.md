# Auction Episode Memory

Shadow observation layer between bar/volume events and cognitive / final context.

## Why this layer exists

Primary engines emit **bar events** (e.g. `BUYING_CLIMAX`, `STOPPING_VOLUME`) and volume responses.
Final context (`calibrated_context` in auction context arbitration) collapses everything into
`LONG_CONTEXT` / `SHORT_CONTEXT` / `OBSERVE`.

That collapse loses auction meaning: climax is not “short”, stopping volume is not “long”.
`auction_episode_memory` records the **auction episode** on each bar without deciding trade context.

## What is not a cognitive state

| Token | Role |
|---|---|
| `BUYING_CLIMAX` | Single-bar / climax **event** (`bar_event`) |
| `SELLING_CLIMAX` | Single-bar climax **event** |
| `STOPPING_VOLUME` | Volume **event**, not market phase |
| `ABSORPTION_RESPONSE` | Effort/response observation |

These are inputs to episode classification. They are **not** `market_state` and **not** final context.

## Volume as effort

`volume_effort` (`LOW` / `NORMAL` / `HIGH` / `EXTREME`) is mapped from existing fields only:

- `volume_class`, `relative_volume`, `climax_state`, `volume_event`

No new microstructure model is invented here. Missing fields → `UNKNOWN`.

`effort_side` (`BUYER` / `SELLER` / `MIXED` / `UNKNOWN`) is a diagnostic guess from event + location.

## Price as result

`price_result` and `follow_through` are **diagnostic**:

- compare close vs previous close (and simple high/low proximity)
- look ahead a few available bars for continuation / failure

They are not structural truth and do not force long-lived cognitive states.

`effort_result` combines effort + price/follow-through into auction language:
`ACCEPTED` / `REJECTED` / `ABSORBED` / `CONTINUED` / `NO_RESULT` / `UNKNOWN`.

## `auction_episode` vs final context

| Layer | Examples | Meaning |
|---|---|---|
| Auction episode | `UPPER_DISTRIBUTION`, `LOWER_ABSORPTION`, `FAILED_BREAKOUT`, `BALANCE` | What the auction is doing |
| Final context | `LONG_CONTEXT`, `SHORT_CONTEXT`, `OBSERVE` | Shadow directional posture (arbitration) |

This builder **never** writes `LONG_CONTEXT` or `SHORT_CONTEXT`.

Example mapping intent (not execution):

- `BUYING_CLIMAX` + `UPPER_AREA` + failed higher follow-through → `UPPER_DISTRIBUTION`
- `STOPPING_VOLUME` + `LOWER_AREA` + no lower follow-through → `LOWER_ABSORPTION`

## Shadow-only

Every row has `shadow_only=True`.

- Not in `CANONICAL_PIPELINE` (this stage)
- Does not modify arbitration, trading_state, or execution
- Safe to rebuild by hand via the research script

## How to run

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_auction_episode_memory.py
```

Output: `data/cognition/auction_episode_memory.parquet`

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_auction_episode_memory.py -q
```
