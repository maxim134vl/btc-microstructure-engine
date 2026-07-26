# Stage 2B1.1A.2 — Liquidity Clusters Restore Candidate

**Status:** `STAGE2B11A2_LIQUIDITY_CLUSTER_CANDIDATE_READY`  
**Generated (UTC):** `2026-07-26T17:05:00Z`  
**HEAD (pre-commit):** `64a8062`  
**Branch:** `memory/canonical-system`  
**Mode:** candidate restore — **no live activation**, **no pipeline registration**, **0 process restarts**

Artifacts: `data/candidate/architecture_recovery/stage2b11a2_liquidity_clusters_restore/`

---

## A. Result

```text
STAGE2B11A2_LIQUIDITY_CLUSTER_CANDIDATE_READY
```

Restored contract (not live-wired):

```text
volume_localization_memory.parquet
→ liquidity_cluster_engine_v1.py
→ data/cognition/liquidity_clusters_memory.parquet
```

---

## B. Stage 1 Health

| Check | Value |
| --- | --- |
| HEAD | `64a8062` |
| PID | `16607` |
| steps | `21` |
| localization / response source | fresh (`16:30` at preflight) |
| join | `EXACT_FRESH_MATCH` |

```text
Stage 1 healthy = true
```

---

## C. Previous Root Cause

```text
hardcoded volume_localization_v2 (May) + CWD output + unregistered path
→ zones 78k–83k vs market ~65k → all-neutral interaction
```

---

## D. Canonical Input Contract

| Item | Value |
| --- | --- |
| File | `liquidity_cluster_engine_v1.py` |
| Was | `"volume_localization_v2_memory.parquet"` |
| Now | `resolve_read("volume_localization_memory.parquet")` |
| Schema compat | required fields present on both v1/v2; same semantics/dtypes |
| Conversion | **none** |

---

## E. Canonical Output Contract

| Item | Value |
| --- | --- |
| Was | CWD `liquidity_clusters_memory.parquet` |
| Now | `resolve_write("liquidity_clusters_memory.parquet")` |
| Registry | `liquidity_clusters_memory.parquet` → `cognition` |
| Live cognition file written this stage | **no** (candidate `BTC_ML_DATA_ROOT` only) |

---

## F. Production Files Changed

| File | Change |
| --- | --- |
| `liquidity_cluster_engine_v1.py` | path-only imports + resolve_read/write |
| `storage/path_registry.py` | +1 mapping |

```text
production files changed = 2
algorithm lines changed = 0
```

Diff (engine): only import + two path strings.

---

## G. Cluster Algorithm Invariance

| Check | Result |
| --- | --- |
| Calculation body text identical | **true** |
| Structural fields A vs B max err | **0** |
| `behaviors` parity | **100%** |
| `dominant_behavior` mismatches | 43 rows |

`dominant_behavior` uses `max(set(x), key=x.count)` — **pre-existing tie nondeterminism**. Not introduced by path change. Deferred; not fixed here.

```text
path-only invariance (structural + behaviors) = accepted
```

---

## H. Candidate Cluster Replay

Frozen input: `frozen_volume_localization_memory.parquet` (5000 rows).

| Metric | Value |
| --- | --- |
| output clusters | **918** |
| zone min–max | **58249.14 – 82684.01** |
| duplicates | 0 |
| invalid zones | 0 |
| SHA256 | `1ffaa5cd…` |

Matches prior audit approximate result on same localization window size.

---

## I. Current Market Zone Coverage

| Metric | Value |
| --- | --- |
| current price | ~64734 |
| clusters containing price | **8** |
| overlap current range | **true** |

---

## J. Candidate Interaction Impact

| Metric | Value |
| --- | --- |
| rows | 3718 |
| matched | **3718** |
| non-neutral | **1434** |
| expansion_into_distribution | 1 |

(Counts differ slightly from audit 1442/9 due to `dominant_behavior` tie flips — branch still exercised.)

---

## K. Candidate HTF/LTF Context

| Metric | Value |
| --- | --- |
| rows | 3714 |
| tip | `2026-07-26 15:45:00+00:00` |
| interaction-derived labels | **44** |

---

## L. Candidate Auction Synthesis

| Metric | Value |
| --- | --- |
| FAILED_EXPANSION | **1** (> 0) |
| branch reachable | **true** |

---

## M. Tests

`tests/test_stage2b11a2_liquidity_clusters_restore.py` + Stage 2B1.1A suite:

```text
relevant tests green
```

Note: tests intentionally avoid `resolve_read` on clusters to prevent `migrate_legacy` copying May CWD into cognition during CI.

---

## N. Deferred Issues

- `STAGE2B11A2-DOMINANT-BEHAVIOR-TIE-NDETERMINISM`
- `STAGE2B11A2-LEGACY-MIGRATE-RISK` — first live `resolve_read` before write could migrate May CWD; activation must write fresh clusters (or remove CWD) first
- Prior: no timestamp/expiry, neutral ambiguity, unused contextual_alignment

---

## O. Git Commit

```text
fix: restore canonical liquidity cluster memory
push = NOT PERFORMED
```

---

## P. Compliance

```text
restarts = 0
live writes = 0
pipeline changes = 0
push = NOT PERFORMED
production files changed = 2
```

Accidental test migrate of May artifact into cognition was **deleted immediately**; final state has no `data/cognition/liquidity_clusters_memory.parquet`.

---

## Q. Next Step

```text
Этап 2B1.1B —
integrated flow + interaction + liquidity clusters
+ HTF + auction synthesis candidate wiring
```

Live activation not performed.
