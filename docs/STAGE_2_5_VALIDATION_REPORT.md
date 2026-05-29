# Stage 2.5 Intermediate Cognition — Retrospective Validation

**Period:** 2026-05-21 → 2026-05-28  
**Engine:** `intermediate_cognition_engine_v1.py`  
**Memory:** `intermediate_cognition_memory.parquet`

---

## 1. Event Count

| Metric | Value |
|--------|------:|
| Stage 2.5 events (period) | **12** |
| Weekly rate (normalized) | **12.0 / week** |
| Stage 2 events (period) | **0** |
| Behavioral gap observable signals | **47** |

---

## 2. Event Distribution

| State | Count |
|-------|------:|
| IC_CONTINUATION_WEAKENING | 5 |
| IC_INITIATIVE_DETERIORATION | 5 |
| IC_ROTATIONAL_PRESSURE | 2 |

---

## 3. Density Target

| Criterion | Result |
|-----------|--------|
| Target | 12–20 events / week |
| Hard min | ≥ 8 |
| Hard max | ≤ 25 |
| **Status** | **OK** (12.0/week) |

---

## 4. Behavioral Gap Comparison

| Layer | May 21–28 |
|-------|-----------|
| Observable intermediate signals (gap analysis) | 47 |
| Stage 2 synthesis updates | 0 |
| Stage 2.5 intermediate events | 12 |
| Narrative continuity restored | **Yes** |

Stage 2.5 emits **deduplicated, anchored** Tier-2 states (4-bar cooldown, per-bar collapse, hourly dedup). The gap analysis counted raw observable structure signals without persistence rules.

**Last Stage 2 anchor:** `LOCAL_EXHAUSTION` @ 2026-05-20 08:30 (trigger: `BUYING_CLIMAX`)

---

## 5. Data Coverage Caveat

`candle_structure_memory.parquet` spans **55 M15 bars** in the validation window (2026-05-21 00:00 → 16:15). Probabilistic layers extend through May 28. Density normalization assumes a 7-day window; full-week calibration will refine as Stage 1 candle memory catches up.

---

## 6. Example Cognition Chain

```
BUYING_CLIMAX
    ↓
LOCAL_EXHAUSTION          (Stage 2 anchor — frozen)
    ↓
IC_INITIATIVE_DETERIORATION
    ↓
IC_CONTINUATION_WEAKENING
    ↓
IC_ROTATIONAL_PRESSURE
    ↓
IC_INITIATIVE_DETERIORATION
    ↓
… (intermediate narrative continues)
    ↓
INTERMEDIATE_REVERSAL       (prior Stage 2 synthesis reference)
```

---

## 7. Acceptance

| Criterion | Pass |
|-----------|:----:|
| Observable narrative continuity between Stage 2 anchors | ✅ |
| Density 12–20/week (≥8 minimum) | ✅ |
| No trading signals (LONG/SHORT/entries/exits) | ✅ |
| Append-mode persistence with cooldown | ✅ |
| **Overall** | **ACCEPTED** |

Full machine-readable report: `docs/STAGE_2_5_VALIDATION_REPORT.json`

Regenerate:

```bash
venv/bin/python3 intermediate_cognition_engine_v1.py --validation-report --start 2026-05-21 --end 2026-05-28
```
