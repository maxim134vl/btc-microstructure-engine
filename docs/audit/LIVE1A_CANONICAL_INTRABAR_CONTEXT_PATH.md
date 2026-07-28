# LIVE1A — Canonical Intrabar Cognition and Context Event Path

## Status

`LIVE1A_CANONICAL_INTRABAR_CONTEXT_PATH_ACTIVE`

## Scope delivered

Live path:

```text
aggTrade + bookTicker
→ causal partial bars M15/M30/H1/H4
→ localize_bar (provisional)
→ evaluate_response_row (shared with volume_response tip)
→ synthesize_provisional_state (existing auction/cognitive/context classifiers)
→ event-time step_lifecycle (N unchanged; age = floor(elapsed/TF))
→ CONTEXT_* journal (append-only)
→ async Parquet/Zstd archival (data/raw_market_events_v2)
```

Not done (by design for LIVE1A):

- paper manager / traders unchanged
- no legacy void / no new paper epoch
- no paper fills / no real execution

## Key modules

| Component | Path |
|-----------|------|
| Partial bars | `src/btc_ml/live/intrabar/partial_bar_state.py` |
| Response evaluator | `src/btc_ml/cognition/volume_response_evaluate.py` |
| Provisional synthesis | `src/btc_ml/live/intrabar/provisional_synthesis.py` |
| Event-time lifecycle | `src/btc_ml/live/intrabar/event_time_lifecycle.py` |
| Context journal | `src/btc_ml/live/intrabar/context_event_journal.py` |
| Pipeline | `src/btc_ml/live/intrabar/cognition_pipeline.py` |
| Service | `scripts/live/run_intrabar_cognition_service.py` |
| Control | `scripts/live/intrabar_cognition_ctl.py` |

## Runtime paths

- Parquet root: `data/raw_market_events_v2`
- Context journal: `data/cognition/intrabar_context_events/`
- Health: `data/runtime/intrabar_cognition_health.json`
- PID: `run/intrabar_cognition.pid`

## Tests

`tests/live/intrabar/test_live1a_intrabar_context_path.py` — 15 passed.
