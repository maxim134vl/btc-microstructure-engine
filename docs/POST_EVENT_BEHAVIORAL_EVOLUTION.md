# POST-EVENT BEHAVIORAL EVOLUTION

**Status:** Phase 3A — evolution-based classification  
**Updated:** 2026-05-27  
**Module:** `post_event_evolution.py`

---

## 1. Purpose

Classify climax events by **what happens after** the event — not only candle geometry — without runtime lookahead dependency.

Uses only subsequent bars already in historical dataset (batch/replay safe).

---

## 2. Exported Metrics

| Field | Meaning |
|-------|---------|
| `climax_resolution_behavior` | Resolved outcome label |
| `absorption_persistence_score` | Mean post-event close position |
| `continuation_failure_rate` | Fraction of post-event bars with negative delta |
| `stabilization_duration` | Consecutive low-decay bars after event |
| `post_climax_entropy_shift` | Efficiency decay shift post-event |
| `inventory_transfer_quality` | Composite absorption/transfer score |
| `capitulation_decay_rate` | Rate of delta aggression decay |

---

## 3. Resolution Labels

### STOPPING_VOLUME
- `ABSORPTION_HELD` — persistence high, continuation failure low
- `ABSORPTION_FAILED` — continuation failure high
- `ABSORPTION_UNRESOLVED` — intermediate

### SELLING_CLIMAX
- `CAPITULATION_CONTINUED` — continuation failure high
- `CAPITULATION_ABSORBED` — recovery/absorption detected
- `CAPITULATION_DECAYING` — intermediate decay

---

## 4. Lookahead Removal

`future_return_3` removed from refined runtime ontology path.

Replacement signals:
- `recovery_structure_score` (intra-candle)
- `close_position_ratio` evolution (post-event)
- `stabilization_duration` (post-event)

Research-only `future_return_3` remains in `research_dataset_builder_v1.py`.

---

## 5. Replay

```bash
venv/bin/python3 scripts/replay_validation/ontology/selling_climax_evolution.py
venv/bin/python3 scripts/replay_validation/ontology/stopping_volume_evolution.py
venv/bin/python3 scripts/replay_validation/ontology/post_event_entropy_decay.py
venv/bin/python3 scripts/replay_validation/ontology/continuation_failure_analysis.py
```
