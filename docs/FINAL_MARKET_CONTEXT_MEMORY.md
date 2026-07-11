# Final Market Context Memory

Shadow top-level market context after `cognitive_market_state_memory`.

## Why this layer exists

Lower layers describe auction episodes and cognitive process states.
This layer publishes the first restored **market context**:

- `LONG_CONTEXT`
- `SHORT_CONTEXT`
- `OBSERVE`

It is the visualization / research answer to: *what market context is active now?*

It is **not** an order, entry, or execution permission.

## Cognitive state vs market context

| Layer | Question | Examples |
|---|---|---|
| `cognitive_market_state` | What process is the market in? | `UPPER_DISTRIBUTION`, `LOWER_ABSORPTION`, `BALANCE` |
| `market_context` | What top-level context does that imply? | `SHORT_CONTEXT`, `LONG_CONTEXT`, `OBSERVE` |

Examples:

- `LOWER_ABSORPTION` → `LONG_CONTEXT`
- `UPPER_DISTRIBUTION` → `SHORT_CONTEXT`
- `BALANCE` / `UNCERTAIN` → `OBSERVE`

## LONG / SHORT here are not trade signals

`LONG_CONTEXT` / `SHORT_CONTEXT` mean research market posture only.

They do **not** mean:

- open a position
- allow live risk
- bypass safety gates

Execution is gated separately.

## `action_allowed` lives apart from `market_context`

| Field | Meaning |
|---|---|
| `market_context` | Market reading |
| `action_allowed` | Whether any action may be taken |

On this stage:

- `action_allowed` is always `False`
- `action_reason` is always `shadow market context only; execution disabled`

A later stage may set action policy without rewriting the market reading.

## Do not erase SHORT_CONTEXT because trading is disabled

If the market reading is short, keep `SHORT_CONTEXT`.

Do **not** force:

- `SHORT_CONTEXT` → `OBSERVE` because of `SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE`
- `SHORT_CONTEXT` → `OBSERVE` because `action_allowed=False`

That confusion destroyed earlier architecture: market truth was overwritten by trade policy.
Here market context and action permission stay separate.

## Visualization of context start / end

Because each bar has an explicit `market_context`, later UI can:

1. scan consecutive bars
2. detect transitions (`OBSERVE` → `LONG_CONTEXT`, `LONG_CONTEXT` → `OBSERVE`, …)
3. paint green/red context intervals from start to end timestamps

`context_status` (`ACTIVE` / `DEVELOPING` / `INVALIDATED` / `OBSERVE`) can style confidence without changing the context label.

## Shadow-only / not in pipeline

- `shadow_only=True`
- not added to `CANONICAL_PIPELINE` in this stage
- does not modify arbitration, dashboard, visualizer, or execution

## How to run

Prerequisite:

```bash
venv/bin/python scripts/research/build_auction_episode_memory.py
venv/bin/python scripts/research/build_cognitive_market_state_memory.py
```

Build:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_final_market_context_memory.py
```

Tests:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_final_market_context_memory.py -q
```

Output: `data/cognition/final_market_context_memory.parquet`
