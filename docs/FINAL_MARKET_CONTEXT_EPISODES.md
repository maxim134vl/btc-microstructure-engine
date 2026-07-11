# Final Market Context Episodes

Shadow episode layer over `final_market_context_memory`.

## Why this layer exists

Bar-level `market_context` answers: *what context is this bar?*

Episodes answer: *where did that context start and end?*

That is what a chart needs to paint:

- green block from LONG start → LONG end
- red block from SHORT start → SHORT end
- no fill for OBSERVE stretches

## How an episode is defined

An episode is a **contiguous run of identical `market_context`**.

Rules:

1. Sort `final_market_context_memory` by `timestamp`
2. Start a new episode on the first row, or when `market_context` changes
3. End the episode on the last row before the next change
4. Keep the context label exactly as stored: `LONG_CONTEXT` / `SHORT_CONTEXT` / `OBSERVE`

No hand-coded lifetime. No “N bars then expire”. No extra invalidation rules.
Only factual context changes.

## Duration

`duration_minutes = (end_time - start_time)` in minutes.

- Single-bar episode → `0.0`
- Multi-bar episode → actual timestamp span between first and last bar

This is a factual span, not a policy lifetime.

## Why not invent state lifetime here

Lifetime lifetime belongs to later analysis of episode sequences.
This file only materializes already-decided context runs so UI/research can draw intervals.

## Chart usage

For each episode row:

- `start_time` / `end_time` → interval bounds
- `market_context` → color / lane
- `bars_count` / `duration_minutes` → labels
- `dominant_context_status` → optional confidence styling
- latest episode with `end_reason = "latest open episode"` → still-open context

## Not a trade signal

Episodes inherit shadow market context only.

- `shadow_only=True`
- `action_allowed_any` / `action_allowed_all` currently expected `False`
- no execution meaning

## Source of truth

Only:

`data/cognition/final_market_context_memory.parquet`

This builder does **not** re-read auction episodes or cognitive states to invent context.
It only groups the already published `market_context`.

## How to run

Prerequisite:

```bash
venv/bin/python scripts/research/build_final_market_context_memory.py
```

Build:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python scripts/research/build_final_market_context_episodes.py
```

Tests:

```bash
cd /Users/fontecrypto/btc-ml && venv/bin/python -m pytest tests/test_final_market_context_episodes.py -q
```

Output: `data/cognition/final_market_context_episodes.parquet`
