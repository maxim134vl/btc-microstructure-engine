# Stage 4B1 — Reinforcement / Probabilistic Cognition Bridge Candidate

**Status:** `STAGE4B1_REINFORCEMENT_PROBABILISTIC_CANDIDATE_READY`  
**UTC:** 2026-07-26  
**Base HEAD:** `5ca7dd1`  
**Live PID (untouched):** `57303`  
**Evidence:** `data/candidate/architecture_recovery/stage4b1_reinforcement_probabilistic_candidate/`

## A. Result

Isolated production candidate restores:

```text
runtime_cognition_memory.parquet
→ auction_reinforcement_engine_v1
→ auction_reinforcement_memory.parquet
→ probabilistic_auction_engine_v1
→ probabilistic_auction_memory.parquet
```

Parent `STATE["runtime_cognition"]` is no longer the source of truth. Live pipeline was **not** restarted.

## B. Stage 1–3 Health

| Check | Value |
| --- | --- |
| `localization_join_status` | `EXACT_FRESH_MATCH` |
| Runtime cognition eval tip (frozen) | `2026-07-26 21:15:00+00:00` |
| Upstream regression | false |
| Pipeline PID | `57303` (26 steps) |

## C. Current Root Cause

Stage 4A: subprocess `runtime_cognition_engine_v1` writes parquet + child STATE; in-process reinforcement/probabilistic read empty parent STATE → `alignment_status=MISSING`, wall-clock tips, invented-neutral narratives.

## D. Reinforcement Source Contract (before)

| Item | Value |
| --- | --- |
| Entry | `run()` |
| Cognition | `STATE.get("runtime_cognition", {})` L63–66 |
| Other STATE | `auction_synthesis`, `volume_response` |
| Parquet | `auction_reinforcement_memory.parquet` history |
| Timestamp | `datetime.utcnow()` |
| Empty dict effect | defaults → persist_comp=0, MISSING align, still writes NEUTRAL_CONVICTION |

## E. Probabilistic Source Contract (before)

| Item | Value |
| --- | --- |
| Entry | `run()` |
| Cognition | `STATE.get("runtime_cognition", {})` L93–96 |
| Reinforcement | `STATE["auction_reinforcement"]` |
| Window | `tail(25)` frequency shares |
| Timestamp | `datetime.utcnow()` |

## F. Canonical Cognition Contract

```text
resolve_canonical("runtime_cognition_memory.parquet")
→ $BTC_ML_DATA_ROOT/cognition/runtime_cognition_memory.parquet
→ live: data/cognition/runtime_cognition_memory.parquet
```

Selection: max UTC `timestamp` (evaluation identity), sort + duplicate-identity reject, required fields:

`persistence_score`, `structural_rank`, `synthesis_state`, `location_bias`

Optional: `alignment_status` (absent in current parquet → source-true `MISSING`), `alignment_score`, lineage/auction timestamps.

No legacy/repo-root fallback (fail-closed if canonical missing).

## G. Production Files Changed

| # | File | Classification |
| ---: | --- | --- |
| 1 | `auction_reinforcement_engine_v1.py` | I/O + timestamp/provenance + fail-closed |
| 2 | `probabilistic_auction_engine_v1.py` | I/O + timestamp/provenance + fail-closed |
| 3 | `runtime_dependency_map.py` | dependency sync |

```text
formula changes = 0
production files changed = 3
fourth production file required = false
```

## H. Parent STATE Removal

Cognition dict is loaded only from canonical parquet. Scenarios:

| Scenario | Result |
| --- | --- |
| Empty STATE | parquet wins |
| Conflicting STATE | output == empty-STATE parquet path (numeric err 0) |
| Invented newer STATE | ignored |

## I. Fail-Closed Behavior

Missing/unreadable/invalid cognition → explicit:

```text
RUNTIME COGNITION UNAVAILABLE
SKIP — missing required runtime cognition evaluation
```

No new reinforcement/probabilistic rows; no NEUTRAL_CONVICTION/UNCERTAIN emission.

## J. Timestamp Identity

```text
reinforcement.timestamp = cognition evaluation timestamp
probabilistic.timestamp = same evaluation timestamp
lineage_event_timestamp = cognition MTF/event lineage (preserved after apply_lineage_metadata)
auction_event_timestamp = cognition auction event (propagated when present)
```

UTC via `pd.to_datetime(..., utc=True)`.

## K. Scenario A — Current Defect

Unpatched engines + empty STATE + fresh parquet:

- `alignment_status=MISSING`
- `persistence_component=0.0`
- wall-clock timestamp
- `belief_strength≈0.478` (live-like empty-STATE baseline)

**Defect reproduced = true**

## L. Scenario B — Fresh Cognition

Patched + empty STATE:

- eval tip `2026-07-26 21:15:00+00:00`
- `persistence_component=0.1`
- `location_component=0.2`
- `belief_strength≈0.573` (differs only via restored cognition evidence)

## M. Scenario C — Conflicting STATE

Output parity vs B: numeric max error `0`, categorical parity `100%`.

## N. Scenario D — Missing Cognition

Canonical unlink under candidate root only:

- new rows `0`
- artifact hashes unchanged
- SKIP reason present
- invented narratives `0`

## O. Scenario E/F — New and Unchanged

| Cycle | Result |
| --- | --- |
| E tip `21:00` → `21:15` | both engines advance exactly |
| F unchanged | new rows `0` |

## P. Scenario G — Auction Transition

Real cognition tips `21:00`/`21:15`: auction_state `NEUTRAL` → `STRUCTURAL_COMPRESSION` loaded from cognition lineage. Formula `auction_state` remains synthesis-sourced (unchanged contract).

## Q. Last-100 Replay

| Metric | Value |
| --- | --- |
| eligible cognition tips | 100 |
| reinforcement evaluations | 100 |
| duplicates | 0 |
| missing | 0 |
| last = latest tip | true |
| probabilistic last tip | matches (final bar) |

## R. Alignment Lineage

| Field | Source |
| --- | --- |
| evaluation timestamp | runtime cognition `timestamp` |
| alignment status | cognition column if present, else source-true `MISSING` (column currently absent) |
| lineage event timestamp | cognition |
| auction event timestamp | cognition |
| structural/persistence/location | cognition |

No inventing `VALID` from score alone.

## S–T. Formula Invariance

Same cognition dict via old STATE transport vs new parquet path:

```text
belief-strength max error = 0
component parity = 100%
classification parity = 100%
```

Frequency-share / window `25` unchanged.

## U. Probability / Confidence Validation

Finite, `[0,1]` bounds on probability-like fields. Sum ≠ 1 (source-true frequency shares). Not renormalized.

## V. Determinism

Twin frozen runs: numeric max error `0`, timestamp/categorical parity `100%`. No RNG seed required.

## W. Dependency Signature

| Cycle | Reinforcement | Probabilistic |
| --- | --- | --- |
| 1 fresh | run | run |
| 2 unchanged | skip | skip |
| 3 new cognition | run | run |
| 4 unchanged again | skip | skip |

Map:

```text
auction_reinforcement_engine_v1.py ← runtime_cognition_memory, auction_synthesis_memory, volume_response_state
probabilistic_auction_engine_v1.py ← runtime_cognition_memory, auction_reinforcement_memory
```

## X. Consumer Compatibility

Arbitration/state_transition required columns present; evaluation timestamp dtype accepted for asof. No consumer code changes. Wall-clock was not a required consumer contract (asof on candle M15 benefits from eval tips).

## Y. Tests

`tests/test_stage4b1_reinforcement_probabilistic_candidate.py` — source-of-truth, fail-closed, timestamp/lineage, dependencies, invariance, duplicates, consumer schema.

Relevant suites green (53 passed including Stage 3 / dependency guard / arbitration / Stage 4B1).

Deferred unrelated failures:

- `test_reinforcement_and_trading_untouched` (expects zero diff on these files — obsolete for 4B1)
- `test_interaction_v3_historical_label_parity` (pre-existing Stage 3 deferred)

## Z. Deferred Issues

Register updated: Stage 4A blockers marked **candidate-ready / pending 4B2 live activation**. Alignment `VALID` enrichment remains deferred (parquet lacks `alignment_status`; not invented here).

## AA. Git Commit

```text
fix: consume current cognition in reinforcement pipeline
```

Push: **NOT PERFORMED**

## AB. Compliance

```text
restarts = 0
live writes = 0
pipeline changes = 0
runtime hardening changes = 0
global dependency guard changes = 0
formula changes = 0
production files changed = 3
push = NOT PERFORMED
```

## AC. Next Step

**Этап 4B2 — controlled live activation of reinforcement / probabilistic cognition bridge** (not executed).
