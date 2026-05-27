# BUYING CLIMAX EXHAUSTION MODEL

**Status:** Phase 3B — observability only, no ontology rewrite  
**Module:** `buying_exhaustion_validation.py`

---

## Hypothesis Under Test

`BUYING_CLIMAX` may represent either:
- True upside exhaustion (high effort + weak continuation), or
- Generic high-volume expansion near highs

## Exports

| Field | Meaning |
|-------|---------|
| `buying_exhaustion_quality` | Composite exhaustion score |
| `upside_continuation_fragility` | Upside continuation failure proxy |
| `breakout_failure_persistence` | Failed breakout persistence |
| `upside_rejection_persistence` | Upper rejection persistence |
| `upper_wick_asymmetry` | Upper wick dominance |

## Replay

```bash
venv/bin/python3 scripts/replay_validation/ontology/buying_climax_exhaustion.py
```
