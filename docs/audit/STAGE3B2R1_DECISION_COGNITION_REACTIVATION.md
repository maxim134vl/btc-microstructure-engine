# Stage 3B2-R1 — Controlled Live Re-Activation

**Status:** `STAGE3_DECISION_COGNITION_LIVE_ACTIVATED`  
**UTC date:** 2026-07-26  
**Branch:** `memory/canonical-system`  
**Activation commit:** `3d9de05` — `fix: restore decision cognition with UTC alignment`  
**Private Gitea tip before push:** `713ef3b`

## A. Result

Decision cognition bridge + UTC-safe alignment merge loaded into live 26-step pipeline via one controlled restart.

```text
old PID = 36571
new PID = 57303 (PPID=1)
natural M15 bars = 3 (20:15, 20:30, 20:45 UTC)
stage2 + runtime cognition = SUCCESS on all bars
UTC merge errors after activation = 0
```

## B. Pre-Activation Stage 1–2 Health

| Check | Result |
| --- | --- |
| `localization_join_status` | `EXACT_FRESH_MATCH` (last 20) |
| Flow / interaction | tip `2026-07-26 20:00Z`; non-neutral present |
| HTF / HTF-LTF | fresh (1-bar lag deferred) |
| Auction synthesis | evaluating |
| Pipeline | PID `36571`, 26 steps, count=1 |

## C. Source Scope

```text
source changes during Stage 3B2-R1 = 0
```

## D. Tests

```text
89 passed
```

Including `tests/test_stage3b11_utc_alignment_candidate.py`.

## E. Launch Contract

Unchanged: Cellar Python 3.11 / `run.py` / `Popen(start_new_session=True)` / `logs/runtime_stack/runtime.log` + `runtime.pid`.

## F. Duplicate-Start Protection

```text
pre-stop=1 → post-stop=0 → post-start=1
duplicate starts = 0
```

## G. Old / New Pipeline PID

| Role | PID |
| --- | --- |
| Pre-activation | `36571` |
| Activation | `57303` |

## H. Runtime Flags

Unchanged Stage 2 flag set (`persistent_worker`, localization=1, synthesis inputs=1, continuation=0).

## I. Pre-Activation Artifact Snapshot

```text
data/quarantine/architecture_recovery/stage3b2r1/20260726_201611/
```

Pre cognition/MTF tip: `2026-07-25 08:45` (167 rows).

## J. First Full Cycle

| Engine | Status |
| --- | --- |
| `stage2_cognition_runtime_v1` | SUCCESS |
| `runtime_cognition_engine_v1` | SUCCESS |
| evaluation tip | `2026-07-26 20:00:00+00:00` (= candle tip) |
| lineage | `2026-07-25 08:45:00+00:00` |
| auction carry | real auction state (`NEUTRAL` from auction artifact at first cycle) |

## K–L. UTC Merge / Timezone

Post-activation: merge `ValueError` count = 0.  
Evaluation timestamps `datetime64[us, UTC]`; lineage/auction event times preserved; no +03/+05/+06 shift observed.

## M. MTF Event Memory Invariance

Rows 167; tip `2026-07-25 08:45`; structural columns parity vs quarantine = true; fabricated events = 0.

## N–P. Freshness / Writer Order / Auction

Tip advances with candle; writer-order regression = 0; auction state consumed from canonical `auction_synthesis` (no invented fallback).

## Q. Consumer Compatibility

Arbitration reads succeed; required cognition columns present; failures = 0.

## R. Three Natural M15 Bars

| Field | Bar 1 | Bar 2 | Bar 3 |
| --- | --- | --- | --- |
| source M15 | 20:15 | 20:30 | 20:45 |
| PID | 57303 | 57303 | 57303 |
| stage2 | SUCCESS | SUCCESS | SUCCESS |
| runtime cognition | SUCCESS | SUCCESS | SUCCESS |
| evaluation tip | 20:15 | 20:30 | 20:45 |
| eval dtype | datetime64[us, UTC] | same | same |
| lineage | 2026-07-25 08:45 | same | same |
| new climax | false | false | false |
| MTF tip/rows | 08:45 / 167 | same | same |
| UTC merge | SUCCESS | SUCCESS | SUCCESS |
| dups | 0 | 0 | 0 |
| false skip | 0 | 0 | 0 |
| alive | true | true | true |

Evidence: `three_bar_gate.json` + runtime.log tip/SUCCESS pairs.

## S–T. Missing/Dups / Dependency

Eligible bars = 3; new eval timestamps = 3; missing = 0; dups = 0; false skip on new candle = 0.

## U. Context / Trading Safety

Lifecycle/trading quarantine SHAs unchanged at first-cycle check; paper-only traders preserved.

## V. Preserved Processes

Manager/traders/OPS/Vite/watchdog/refreshers alive. Feed v2 natural watchdog bounce 96152→82711 recorded deferred.

## W. Deferred Issues

- `STAGE3B2R1-INTERMEDIATE-TZ-COMPARE` (intermediate engine UTC compare fail; out of Stage 3 decision scope)
- `STAGE3B2R1-FEED-V2-WATCHDOG-BOUNCE`

## X. Git / Private Gitea

Docs commit + push of `3d9de05` (+ docs) to `gitea` `memory/canonical-system`. GitHub push NOT PERFORMED.

## Y. Compliance

```text
pipeline intentional restarts = 1
rollback restarts = 0
duplicate starts = 0
other deliberate restarts = 0
source changes during activation = 0
GitHub push = NOT PERFORMED
```

## Z. Next Step

Этап 4 — reinforcement / probabilistic integrity (not executed).
