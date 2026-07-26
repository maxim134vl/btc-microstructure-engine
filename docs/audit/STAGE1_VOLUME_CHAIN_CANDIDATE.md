# Stage 1A — Volume Chain Candidate

**Status:** `STAGE1_VOLUME_CHAIN_CANDIDATE_READY`  
**Generated (UTC):** `2026-07-26T14:16:00Z`  
**Branch:** `memory/canonical-system`  
**Baseline HEAD:** `d7e2a56`  
**Mode:** candidate only — **no live activation**, **no process restart**, **no live cognition writes**

---

## A. Result

```text
STAGE1_VOLUME_CHAIN_CANDIDATE_READY
```

Proven candidate restores:

```text
candle_structure → volume_localization → volume_response
```

Live `CANONICAL_PIPELINE` remains **20 steps** (localization unregistered). Flag default stays `BTC_ML_VOLUME_LOCALIZATION_LIVE=0`.

---

## B. Baseline Verification

| Check | Value |
| --- | --- |
| `git rev-parse HEAD` | `d7e2a56b19adca158324749b8fb4e32d3dd0f97c` |
| branch | `memory/canonical-system` |
| baseline_manifest SHA256 | `a2b6905c2fe16a0a065ccdecf56853f342ae2658278d1b4b406ef0d095b64422` |
| baseline hash verified | **true** |

Dirty tree left untouched (pre-existing benchmark/dashboard noise not cleaned).

---

## C. Current Root Cause

Audit break (still true on live tip at Stage 1A verification):

| Layer | Live fact |
| --- | --- |
| `candle_structure` | ACTIVE_FRESH — tip `2026-07-26 13:30:00+00:00`, dups=0, median gap 900s |
| `volume_localization` | SOURCE present; **not in live pipeline**; tip frozen `2026-07-26 11:00:00+00:00` |
| `volume_response` | RUNNING; `source_candle_timestamp` tip still `11:00`; only 2 rows have EXACT_FRESH_MATCH from prior aborted activation |

**Root cause:** localization engine exists and matches proven algorithm `volume_localization_v1@8fbde36`, but:

1. not registered in live `CANONICAL_PIPELINE` (20 steps),
2. `volume_localization_memory.parquet` was unregistered in path registry → `safe_read` could miss cognition path,
3. with flag off, response reads stale `volume_localization_v2` tip-carry; with flag on, persist previously could skip writing `source_candle_timestamp` when behavior label unchanged.

Stage 1A fixes (1)/(2)/(3) as **candidate readiness** only — does **not** activate pipeline or set the live flag.

---

## D. Candle Timestamp Contract

| Item | Contract |
| --- | --- |
| Producer | `candle_structure_engine_v1.py` (unchanged) |
| Canonical input | live market / structure inputs (existing) |
| Canonical output | `data/cognition/candle_structure_memory.parquet` |
| Timestamp meaning | completed M15 **bar-open** |
| Timezone | UTC |
| M15 filtering | 15-minute cadence; tip verification median gap = 900s |
| Latest tip (verify) | `2026-07-26 13:30:00+00:00` |
| Duplicate count | 0 |
| Downstream key | `candle_structure.timestamp == canonical completed M15 bar-open` |

**No candle_structure changes.** No `STAGE1_CANDLE_IDENTITY_CONFLICT`.

---

## E. Localization Contract

| Item | Value |
| --- | --- |
| Package impl | `src/btc_ml/cognition/volume_localization_engine_v1.py` |
| Thin wrapper | `volume_localization_engine_v1.py` (repo root) |
| Algorithm | `volume_localization_v1@8fbde36` — **unchanged** |
| Input | `candle_structure_memory.parquet` |
| Output | `data/cognition/volume_localization_memory.parquet` |
| Primary key | `timestamp` (= source candle bar-open) |
| Fields | `estimated_local_volume`, `volume_concentration`, `zone_low/high/width`, `behavior` |
| Formulas | `elv = volume × ratio` (body 0.5 / wick 0.7); concentration = elv/(volume+eps); absorption/distribution/body classification |
| Join helper | `resolve_localization_for_structure` — exact equality only; no `merge_asof` / ffill / bfill |
| Persistence | atomic parquet replace; retention 5000 |

**No formula changes.** No `STAGE1_LOCALIZATION_CONTRACT_DRIFT`.

---

## F. Volume Response Contract

| Item | Behavior |
| --- | --- |
| Engine | `volume_response_engine_v1.py` |
| Flag off (live default) | reads `_LOCALIZATION_V2`; join status `LEGACY_V2_TIP_CARRY` (unchanged legacy) |
| Flag on (Stage 1B) | reads `_LOCALIZATION_V1`; exact join via `resolve_localization_for_structure` |
| Identity | `source_candle_timestamp` = bar-open; `source_candle_close` = +15m; `evaluated_at` = wall-clock |
| Join key | `source_candle_timestamp == volume_localization.timestamp` |
| Non-exact | localized fields null; statuses `NO_/AMBIGUOUS_/STALE_LOCALIZATION_MATCH` — **no stale carry** when live-v1 |
| Persist fix (Stage 1A) | when flag on, `state_payload` includes `source_candle_timestamp` + `localization_join_status` so tip identity persists even if behavior label unchanged |
| Formulas | effort/result/absorption/continuation/unfinished **untouched** |

---

## G. Production Files Changed

| File | Why required |
| --- | --- |
| `storage/path_registry.py` | Registers canonical `volume_localization_memory.parquet` → `cognition`. Without it, `safe_read` can miss the live cognition artifact. Fixes audit `SOURCE_PRESENT_UNREGISTERED` path half. |
| `volume_response_engine_v1.py` | Ensures persist-by-source-identity when live-v1 flag is later enabled. Without it, exact join can compute but never land in state when behavior is unchanged. |

**Not changed (already present):**

- `src/btc_ml/runtime/pipeline.py` — candidate helper `canonical_pipeline_with_volume_localization_candidate()` already yields 21-step order; live list stays 20.
- `volume_localization_engine_v1.py` / package impl — formulas already match proven contract.

**Production files changed = 2 (≤ 4).** No scope expansion stop.

---

## H. Candidate Pipeline Order

Live (`CANONICAL_PIPELINE`, still active in PID 21945):

```text
20 steps — volume_localization_engine_v1.py ABSENT
```

Candidate (`canonical_pipeline_with_volume_localization_candidate()`):

```text
candle_structure_engine_v1.py
→ volume_localization_engine_v1.py   # inserted
→ volume_classification_engine_v1.py
→ … (unchanged remainder)
→ volume_response_engine_v1.py
```

Candidate length = 21. Other engine order preserved.

---

## I. Canonical Path

```text
data/cognition/volume_localization_memory.parquet
```

Path registry mapping added. Not used as live source for Stage 1A writes:

- `volume_localization_v2_memory.parquet`
- July-10 orphan semantics as activation target
- May-13 stale artifacts

Candidate replay writes **only** under:

```text
data/candidate/architecture_recovery/stage1_volume_chain/
```

---

## J. 5,000-Row Replay

Artifact: `data/candidate/architecture_recovery/stage1_volume_chain/replay_summary.json`

| Gate | Result |
| --- | --- |
| eligible rows | **5200** (≥ 5000) |
| EXACT_FRESH_MATCH | **5200 / 100%** |
| NO_LOCALIZATION_MATCH | 0 |
| AMBIGUOUS_LOCALIZATION_MATCH | 0 |
| STALE_LOCALIZATION_MATCH | 0 |
| duplicate localization timestamps | 0 |
| duplicate response source timestamps | 0 |
| localization.timestamp == response.source_candle_timestamp | 100% |

Outputs:

- `candidate_localization.parquet`
- `candidate_volume_response_identity.parquet`

Live cognition mtimes unchanged by replay (`loc` tip still `11:00`).

---

## K. Three Candidate Bars

| Field | Bar 1 | Bar 2 | Bar 3 |
| --- | --- | --- | --- |
| candle timestamp | 2026-07-26 13:00:00+00:00 | 2026-07-26 13:15:00+00:00 | 2026-07-26 13:30:00+00:00 |
| localization timestamp | 2026-07-26 13:00:00+00:00 | 2026-07-26 13:15:00+00:00 | 2026-07-26 13:30:00+00:00 |
| response source timestamp | 2026-07-26 13:00:00+00:00 | 2026-07-26 13:15:00+00:00 | 2026-07-26 13:30:00+00:00 |
| join status | EXACT_FRESH_MATCH | EXACT_FRESH_MATCH | EXACT_FRESH_MATCH |
| ELV parity | true | true | true |
| concentration parity | true | true | true |
| behavior parity | true | true | true |
| duplicates | 0 | 0 | 0 |
| stale carry | false | false | false |

Acceptance: **3/3** exact match, timestamp equality, parity, zero duplicates/stale carry.

---

## L. Behavioral Parity

Compared 5200 candidate localization rows vs proven algorithm contract:

| Metric | Result |
| --- | --- |
| elv max error | 0.0 |
| concentration max error | 0.0 |
| zone_low/high/width max error | 0.0 |
| behavior exact parity | **100%** |

No `STAGE1_BEHAVIORAL_PARITY_FAILURE`.

---

## M. Response Invariance

Diff in `volume_response_engine_v1.py` only adds identity fields into `state_payload` under live-v1 flag. Untouched:

- `effort_result_state`
- absorption / continuation / unfinished auction
- directional deterioration
- volume classification / climactic inputs

Allowed additive identity fields when live-v1 later enabled:

- `source_candle_timestamp`, `source_candle_close`, `evaluated_at`
- `localization_join_status`, fresh localization ELV/concentration/behavior

---

## N. Tests

| Suite | Result |
| --- | --- |
| `tests/test_stage1a_volume_chain_candidate.py` | pass |
| `tests/test_volume_localization_live_wiring_candidate.py` | pass |
| `tests/test_volume_response_canonical_timestamp_identity.py` | pass |
| `tests/test_volume_localization_shadow_restoration.py` | pass |
| `tests/test_candle_structure_parquet_atomicity.py` | pass |
| `tests/test_atomic_parquet_write.py` | pass |
| `tests/test_runtime_dependency_guard.py` | pass |

Relevant aggregate: **green**. No unrelated failures fixed.

---

## O. Deferred Issues

See `docs/audit/DEFERRED_ISSUES_REGISTER.md`.

None of dual-feed / OI / synthesis / H4 books / UI / launcher / log-rotation block Stage 1A.

---

## P. Git Commit

Message:

```text
fix: prepare canonical volume localization response chain
```

Scope: Stage 1A files only. Push: **NOT PERFORMED**.

---

## Q. Live Compliance

| Constraint | Value |
| --- | --- |
| process restarts | 0 |
| process starts | 0 |
| process stops | 0 |
| live pipeline PID | 21945 still running (pre-existing) |
| live parquet writes by task | 0 (candidate dir only) |
| synthesis / MTF / reinforcement / probabilistic / context / trading / dashboard changes | 0 |
| push | NOT PERFORMED |

---

## R. Next Step

```text
Этап 1B — controlled live activation and three natural M15 bars
```

Stage 1B **not** executed in this stage.
