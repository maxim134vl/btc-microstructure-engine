# Stage 2B1.1A — Flow / Liquidity Interaction Candidate

**Status:** `STAGE2B11A_FLOW_INTERACTION_CANDIDATE_READY`  
**Generated (UTC):** `2026-07-26T16:20:00Z`  
**HEAD (pre-commit):** `2eba9cf`  
**Branch:** `memory/canonical-system`  
**Mode:** candidate only — **no live activation**, **no pipeline registration**, **0 process restarts**

Evidence / artifacts: `data/candidate/architecture_recovery/stage2b11a_flow_interaction_candidate/`

---

## A. Result

```text
STAGE2B11A_FLOW_INTERACTION_CANDIDATE_READY
```

Proven chain (research-only under candidate `BTC_ML_DATA_ROOT`):

```text
live_market_feed
→ live_volume_flow (canonical cognition path)
→ flow_liquidity_interaction (canonical cognition path)
→ nonempty ∩ with htf_structure
→ htf_ltf_context tip advances beyond 2026-05-13
```

---

## B. Stage 1 Health

| Check | Value |
| --- | --- |
| HEAD | `2eba9cf` |
| branch | `memory/canonical-system` |
| pipeline PID | `16607` (alive) |
| process count | `1` |
| steps | `21` |
| candle / localization / response source | `2026-07-26 16:00:00+00:00` |
| `localization_join_status` | `EXACT_FRESH_MATCH` |

```text
Stage 1 healthy = true
```

---

## C. Flow Source Contract

| Item | Value |
| --- | --- |
| Canonical source | `live_volume_flow_engine_v1.py` |
| Entrypoint | top-level script |
| Input | `resolve_read("live_market_feed.parquet")` |
| Required columns | `timestamp`, `open`, `high`, `low`, `close`, `volume` |
| Output | `resolve_write("live_volume_flow_memory.parquet")` → `data/cognition/` |
| Timestamp field | `timestamp` from feed bar identity |
| Timestamp semantics | **bar-open / feed bar identity** (M15, gap 900s) |
| Primary key | `timestamp` (one row per feed bar) |
| Persist mode | **full rewrite** |
| Formulas | unchanged (thresholds 1.8/1.5/0.8/…) |

### Behavior map

| Lines | Behavior |
| --- | --- |
| load feed via registry | path-only |
| L22–80 | spread, price_change, rolling ratios |
| L86–200 | flow_state classification |
| save via `resolve_write` | path-only |

---

## D. Interaction Source Contract

| Item | Value |
| --- | --- |
| Canonical source | **`flow_liquidity_interaction_engine_v3.py`** |
| Registry / orchestrators | `system_registry.yaml` + legacy orchestrators → **v3** |
| Rejected | **v1** — `abs(price)` bug, missing `market_level`; **v2** — near-identical, not registered |
| Inputs | flow + feed via `resolve_read`; clusters via `resolve_read("liquidity_clusters_memory.parquet")` (unregistered → repo root) |
| Output | `resolve_write("flow_liquidity_interaction_memory.parquet")` → `data/cognition/` |
| Schema | `timestamp`, `market_level`, `flow_state`, `matched_cluster`, `interaction_type` |
| Timestamp | exact flow/feed bar identity (skip if timestamp absent from feed) |
| Persist mode | **full rewrite** |
| Formulas | unchanged (inside-cluster zone match) |

Historical May artifact schema matches **v3** (has `market_level`; `matched_cluster` int).

---

## E. Current Path Mismatch

**Before this stage:**

| Writer | Path |
| --- | --- |
| flow / interaction engines | hardcoded CWD `*.parquet` |
| `htf_ltf_context` reader | `resolve_read` → `data/cognition/…` |

CWD copies existed and matched May cognition tips — live wiring without path fix would still miss canonical reads after a fresh CWD-only write.

---

## F. Canonical Path Contract

| Artifact | `resolve_write` / `resolve_read` |
| --- | --- |
| `live_volume_flow_memory.parquet` | `data/cognition/live_volume_flow_memory.parquet` |
| `flow_liquidity_interaction_memory.parquet` | `data/cognition/flow_liquidity_interaction_memory.parquet` |

```text
writer path = reader path = path_registry cognition path
path_registry.py changed = 0 (keys already present)
```

No CWD copies, no symlinks as production solution.

---

## G. Production Files Changed

| File | Change |
| --- | --- |
| `live_volume_flow_engine_v1.py` | path-only: `resolve_read` / `resolve_write` |
| `flow_liquidity_interaction_engine_v3.py` | path-only: `resolve_read` / `resolve_write` |
| `storage/path_registry.py` | **unchanged** |

```text
production files changed = 2 (<= 3)
flow algorithm changed = 0
interaction algorithm changed = 0
pipeline files changed = 0
HTF files changed = 0
```

---

## H. Candidate Flow Replay

| Metric | Value |
| --- | --- |
| eligible input rows | 3718 |
| output rows | 3718 |
| first | `2026-06-15 17:30:00+00:00` |
| last | `2026-07-26 16:00:00+00:00` |
| duplicates | 0 |
| stale May carry | 0 |
| monotonic | true |
| tip > May 13 | **true** |

Warmup NaN ratios: 19 rows (rolling 20) — expected; not missing timestamps.

---

## I. Candidate Interaction Replay

| Metric | Value |
| --- | --- |
| output rows | 3718 |
| first / last | same as flow |
| duplicates | 0 |
| stale May carry | 0 |
| tip > May 13 | **true** |
| `interaction_type` counts | all `neutral` (3718) |

**Note:** `liquidity_clusters_memory.parquet` zones are May-era (~80k); current feed ~64k → no inside-cluster hits. Formulas unchanged; non-neutral labels deferred (see Deferred). Context still advances via flow_state ∩ HTF rules.

---

## J. Formula / Historical Parity

| Check | Result |
| --- | --- |
| Flow feature→label self-parity (May artifact) | **1.0** |
| Flow feature→label self-parity (candidate) | **1.0** |
| Interaction v3 vs May labels (via stored `market_level`) | **1.0** (n=1054) |
| Row-level May feed overlap | **0** (live feed starts 2026-06-15) |

```text
contract compatible = true
row-level May feed parity = unavailable (documented)
```

---

## K. Timestamp Compatibility

| Layer | Semantics |
| --- | --- |
| feed | M15 bar identity |
| flow | = feed timestamp |
| interaction | = flow timestamp (exact feed index lookup) |
| htf_structure | window-end = last M15 of rolling 4 |
| context intersection | exact set ∩ of the three |

No `merge_asof` / ffill / synthetic timestamps.

---

## L. Intersection with HTF Structure

| Metric | Value |
| --- | --- |
| intersection rows | **3714** |
| first | `2026-06-15 18:15:00+00:00` |
| last | `2026-07-26 15:45:00+00:00` |
| tip > May 13 | **true** |

---

## M. Candidate HTF/LTF Context

Research-only `htf_ltf_context_engine_v1.py` on candidate inputs (no live write):

| Metric | Value |
| --- | --- |
| rows | 3714 |
| tip | `2026-07-26 15:45:00+00:00` |
| duplicates | 0 |
| alignments | neutral 3211 / nested_compression 409 / aligned_expansion 94 |

```text
context tip > May 13 = true
```

---

## N. Tests

`tests/test_stage2b11a_flow_interaction_candidate.py`

```text
15 passed
```

---

## O. Deferred Issues

See `docs/audit/DEFERRED_ISSUES_REGISTER.md`:

- `STAGE2B11A-LIQUIDITY-CLUSTERS-STALE` — zones not refreshed; candidate interaction labels all neutral
- Prior HTF wiring / synthesis items unchanged

---

## P. Git Commit

```text
fix: prepare canonical flow inputs for HTF context
push = NOT PERFORMED
```

---

## Q. Compliance

| Rule | Value |
| --- | --- |
| process restarts / starts / stops | **0** |
| live parquet writes | **0** |
| trading writes | **0** |
| pipeline / hardening changes | **0** |
| HTF / synthesis / MTF / trading changes | **0** |
| push | **NOT PERFORMED** |

---

## R. Next Step

```text
Этап 2B1.1B —
integrated flow + interaction + HTF + synthesis candidate wiring
```

Do **not** execute 2B1.1B in this stage. Do **not** activate live pipeline.
