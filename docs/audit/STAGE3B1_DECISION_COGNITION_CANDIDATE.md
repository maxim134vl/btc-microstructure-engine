# Stage 3B1 — Decision Cognition Bridge Candidate

**Status:** `STAGE3B1_DECISION_COGNITION_CANDIDATE_READY`  
**Date (UTC):** 2026-07-26  
**HEAD (pre-commit base):** `713ef3b`  
**Live pipeline:** PID `61126` unchanged (26 steps; no restart)  
**Evidence:** `data/candidate/architecture_recovery/stage3b1_decision_cognition_candidate/`

---

## A. Result

Isolated production candidate ready: event-sparse `multi_timeframe_synthesis` preserved; `runtime_cognition_memory` becomes evaluation-time decision snapshots carrying latest climax/MTF state + latest valid `auction_synthesis` state.

Live artifacts untouched (cog/MTF tip still `2026-07-25 08:45`, 167 rows).

---

## B. Stage 1–2 Health

| Check | Status |
| --- | --- |
| PID 61126 / count=1 / steps=26 | PASS |
| localization join | `EXACT_FRESH_MATCH` |
| flow / clusters / interaction / HTF / auction | healthy / fresh |

---

## C. Selected Integration Path

**Path B — minimally extend `stage2_cognition_runtime_v1.py`**

Proven contract:

- stage2 is the sole writer of both `multi_timeframe_synthesis` and `runtime_cognition_memory`
- Path A alone cannot work: stage2 overwrites cognition each cycle before `runtime_cognition_engine_v1` runs
- Architecture name/role: Stage-2 cognition runtime combines climax MTF memory with auction cognition for decision export

Also updated:

- `runtime_dependency_map.py` (stage2 + runtime_cognition deps match reads)
- `runtime_cognition_engine_v1.py` (STATE hydrate for auction bridge fields)

---

## D. Event Memory Contract

| Artifact | Semantics | Tip (candidate) |
| --- | --- | --- |
| climax → MTF | event-sparse structural memory | **2026-07-25 08:45** (167 rows) |
| fabricated climax/MTF events | **0** | — |
| historical MTF categorical/numeric parity | **100% / max err 0** | vs frozen |

---

## E. Runtime Snapshot Contract

| Field | Semantics |
| --- | --- |
| `timestamp` | **evaluation bar** (candle identity) |
| `lineage_event_timestamp` | climax/MTF **event** time |
| MTF domain fields | carried from latest event ≤ evaluation |
| `auction_state` / `auction_event_timestamp` | latest valid auction asof evaluation (+ tip skew carry) |
| Persistence | full rewrite of evaluation snapshots |
| Path | `data/cognition/runtime_cognition_memory.parquet` |

Candidate tip: **2026-07-26 19:00** (6994 evaluation rows, dups=0).

---

## F. Production Files Changed (3)

1. `stage2_cognition_runtime_v1.py`
2. `runtime_dependency_map.py`
3. `runtime_cognition_engine_v1.py`

Pipeline / hardening: **0**.

---

## G. Actual Inputs

| Input | Required | Read mode | Timestamp semantics |
| --- | ---: | --- | --- |
| candle_structure | yes | evaluation grid | M15 bar-open |
| multi_timeframe_synthesis (built in-cycle) | yes | asof backward | climax event time |
| auction_synthesis | yes (fail-open NA if missing) | asof + tip skew carry | wall-clock event-sparse |

---

## H. Auction State Carry

- `merge_asof(..., direction="backward")` onto evaluation bars
- Same-cycle wall-clock skew: if latest auction ts > tip evaluation bar, attach latest auction to tip row only
- Missing auction → `auction_state=NA` (no invented NEUTRAL)

---

## I–L. Scenarios

| Scenario | Result |
| --- | --- |
| A current behavior | MTF+cog tip 2026-07-25 08:45 vs candle 19:00 (stale) |
| B decision bridge | cog tip=candle tip 19:00; MTF tip unchanged; auction NEUTRAL on tip |
| C auction transition | BALANCED_DISTRIBUTION → NEUTRAL consumed; MTF unchanged |
| D no climax change | evaluation advances; `lineage_event_timestamp` stable at 2026-07-25 08:45 |

---

## M. MTF Event Memory Invariance

```text
row count parity = 100%
categorical parity = 100%
numeric max error = 0
event timestamp parity = 100%
```

---

## N. Runtime Evaluation Freshness

```text
evaluation rows = 6994
first = 2026-05-02 14:30
last = 2026-07-26 19:00
duplicates = 0
missing last 100 eligible bars = 0
```

---

## O. Decision Lineage (tip row)

| Field | Source |
| --- | --- |
| evaluation timestamp | candle 2026-07-26 19:00 |
| lineage_event_timestamp | MTF/climax 2026-07-25 08:45 |
| MTF state | INTERMEDIATE_REVERSAL / STOPPING_VOLUME / … |
| auction_event_timestamp | 2026-07-26 19:15:35 |
| auction_state | NEUTRAL |

Unknown provenance: **0**.

---

## P. Dependency Signature

| Cycle | Result |
| --- | --- |
| 1 fresh | execute |
| 2 unchanged | SKIP (`DEPENDENCY_SIGNATURE_UNCHANGED`) |
| 3 candle mtime change | execute |

`false skip on new bar = 0` (via candle dependency).

---

## Q. Consumer Compatibility

- MTF columns for `timeframe_state_adapter`: OK
- cognition columns for arbitration asof (`timestamp`, `trigger_event`, `location_bias`): OK
- decision tip no longer equals stale MTF tip

---

## R. Tests

`tests/test_stage3b1_decision_cognition_candidate.py` + related suites green.

---

## S. Deferred

Register updated: Stage 3A blockers marked candidate-ready; live activation deferred to 3B2.

---

## T. Git

Commit: `fix: prepare current decision cognition from auction state`  
Push: **NOT PERFORMED**

---

## U. Compliance

```text
restarts = 0
live writes = 0
pipeline changes = 0
push = NOT PERFORMED
production files <= 3
```

---

## V. Next Step

**Этап 3B2 — controlled live activation of decision cognition bridge** (не выполнять).
