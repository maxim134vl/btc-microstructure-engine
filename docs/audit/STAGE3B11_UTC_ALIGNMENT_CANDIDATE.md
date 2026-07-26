# Stage 3B1.1 — UTC Alignment Merge Candidate

**Status:** `STAGE3B11_UTC_ALIGNMENT_CANDIDATE_READY`  
**UTC date:** 2026-07-26  
**Branch:** `memory/canonical-system`  
**Base HEAD:** `739d57a` (revert of `063e03d`)  
**Candidate commit message:** `fix: restore decision cognition with UTC alignment`  
**Live activation:** NOT PERFORMED  
**Push:** NOT PERFORMED

## A. Result

Restored exact Path B bridge from `063e03d` and fixed the Stage 3B2 first-cycle blocker in `runtime_integrity.py` by normalizing merge-key timestamps to timezone-aware UTC immediately before `enrich_alignment_status()` merge (and matching drift comparisons).

Isolated candidate proves:

```text
stage2_cognition_runtime_v1 = SUCCESS
runtime_cognition_engine_v1 = SUCCESS
evaluation tip = latest eligible candle tip
lineage_event_timestamp preserved
auction state carried
```

## B. Stage 1–2 Health

Pre-change live PID `36571` (26 steps):

| Check | Result |
| --- | --- |
| `localization_join_status` | `EXACT_FRESH_MATCH` |
| Flow / interaction tip | `2026-07-26 19:45Z` (non-neutral present) |
| HTF / HTF-LTF | fresh (1-bar lag deferred) |
| Auction synthesis | evaluating (`STRUCTURAL_COMPRESSION`) |
| Runtime cognition tip (live) | still `2026-07-25 08:45` (bridge not live) |

## C. Rollback State

Live remained on reverted bridge (`739d57a`). No process restart. Live cognition artifacts not written by this stage.

## D. Bridge Restoration

```bash
git revert --no-commit 739d57a
```

| File | Parity with `063e03d` |
| --- | --- |
| `stage2_cognition_runtime_v1.py` | 100% |
| `runtime_dependency_map.py` | 100% |
| `runtime_cognition_engine_v1.py` | 100% |

Unexpected additional production files restored: **0**.

## E. Failing Merge Sources

| Side | Artifact | Producer | Timestamp semantics | Dtype at failure |
| --- | --- | --- | --- | --- |
| left | `runtime_cognition_memory.parquet` | `stage2_cognition_runtime_v1` (Path B) | current M15 evaluation bar identity | `datetime64[us, UTC]` |
| right | `multi_timeframe_synthesis.parquet` | `stage2_cognition_runtime_v1` MTF export | MTF/climax **event** bar identity (event-sparse) | `datetime64[us]` naive |

Merge: `enrich_alignment_status()` left-join on `timestamp`.

## F. Timestamp Semantics

**Aware side (left):** introduced by Stage 3B1 bridge:

```text
stage2_cognition_runtime_v1.py
domain["timestamp"] = pd.to_datetime(evaluation_timestamps, utc=True)
```

Evaluation bars come from candle structure (UTC market bars).

**Naive side (right):** pre-existing MTF event memory timestamps written without tz. Proven UTC because:

- same wall-clock values as candle/climax event times throughout the system
- `pd.to_datetime(..., utc=True)` attaches UTC with **epoch shift = 0**
- Asia/Almaty local TZ does not change merge results after normalization

Timezone mismatch **appeared because of the bridge** (left became UTC-aware while right stayed naive). Old both-naive path merged successfully.

## G. Root Cause

```text
ValueError: merge on datetime64[us, UTC] vs datetime64[us] for key 'timestamp'
```

Secondary failure after merge fix alone: `compute_drift_metrics()` subtracted naive synthesis tip from aware cognition tip — fixed in the same file with the same UTC normalize helper.

## H. UTC Normalization Contract

New helper: `normalize_utc_merge_timestamp()`

- `pd.to_datetime(..., utc=True)` only after UTC provenance proof
- aware instants do not shift
- naive UTC wall-clock receives UTC tz without clock shift
- non-null → NaT / unparseable → explicit `ValueError`
- local copies only; input DataFrames not mutated
- only merge-key `timestamp` normalized (not lineage/auction event semantics)

## I. Production Files Changed

Relative to `739d57a`:

1. `stage2_cognition_runtime_v1.py` — exact `063e03d` restore  
2. `runtime_dependency_map.py` — exact `063e03d` restore  
3. `runtime_cognition_engine_v1.py` — exact `063e03d` restore  
4. `runtime_integrity.py` — UTC merge/drift normalize (**only new semantic change**)

Fifth production file: **none**.

## J. Failure Reproduction

Scenario A (`data/candidate/.../stage3b11_utc_alignment_candidate/`):

```text
bridge restored + runtime_integrity unpatched
→ stage2 SUCCESS
→ enrich_alignment_status ValueError (same tz merge message)
```

## K. Patched Candidate Replay

Scenario B (same frozen quarantine inputs under `BTC_ML_DATA_ROOT`):

```text
stage2 SUCCESS
runtime_cognition_engine SUCCESS
evaluation tip = 2026-07-26 19:15:00+00:00
lineage_event_timestamp = 2026-07-25 08:45:00+00:00
auction_state = STRUCTURAL_COMPRESSION
auction_event_timestamp = 2026-07-26 19:30:37.612869+00:00
duplicates = 0
```

## L. Writer Order

| Point | Tip |
| --- | --- |
| after stage2 writer | `2026-07-26 19:15:00+00:00` |
| after runtime cognition engine | `2026-07-26 19:15:00+00:00` |
| end of candidate cycle | `2026-07-26 19:15:00+00:00` |

Tip regression = 0. Runtime engine does not rewrite parquet tip back to `2026-07-25 08:45`.

## M. MTF Event Memory Invariance

| Check | Result |
| --- | --- |
| rows | 167 → 167 |
| structural columns vs quarantine | **equal** |
| fabricated climax/MTF events | 0 |
| SHA256 | changes only via `lineage_propagation_timestamp` wall-clock on rewrite |

## N. Runtime Cognition Freshness

Last 100 eligible M15 bars: missing = 0, duplicates = 0, last evaluation = candle tip.

## O. Auction State Carry

Latest valid auction `STRUCTURAL_COMPRESSION` carried; event timestamp preserved; evaluation tip advances independently; no invented `NEUTRAL`.

## P. Timezone Value Invariance

```text
naive UTC epoch shift = 0
aware UTC epoch shift = 0
Asia/Almaty influence on merge = 0
```

## Q. Dependency Signature

`runtime_dependency_map.py` restored exactly from `063e03d` (candle + auction deps for stage2; cognition + MTF for runtime engine). No extra map edits.

## R. Consumer Compatibility

Research-only on candidate cognition: required columns present; evaluation tip current; lineage/auction preserved; consumer failures = 0. Live context not started.

## S. Tests

```text
tests/test_stage3b11_utc_alignment_candidate.py → 12 passed
Stage 3B1 + dependency + arbitration + atomicity + stage1/2 suites → green
```

Deferred irrelevant: interaction historical label parity live flake (unchanged).

## T. Deferred Issues

`STAGE3B2-ALIGNMENT-TZ-MERGE` addressed by this candidate (pending live re-activation). See register.

## U. Git Commit

One local commit restoring bridge + UTC fix. Push NOT PERFORMED.

## V. Compliance

```text
restarts = 0
live writes = 0
pipeline changes = 0
push = NOT PERFORMED
production files = 4
```

## W. Next Step

**Этап 3B2-R1 — controlled live re-activation** of decision cognition bridge. Do not activate in this stage.
