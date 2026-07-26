# Stage 2B1.1B — Integrated Auction Synthesis Candidate

**Status:** `STAGE2B11B_INTEGRATED_SYNTHESIS_CANDIDATE_READY`  
**Generated (UTC):** `2026-07-26T17:15:00Z`  
**HEAD (pre-commit):** `9e2186d`  
**Branch:** `memory/canonical-system`  
**Mode:** candidate only — **default live pipeline unchanged (21)**, **0 restarts**, **0 live cognition writes**

Artifacts: `data/candidate/architecture_recovery/stage2b11b_integrated_synthesis_candidate/`

---

## A. Result

```text
STAGE2B11B_INTEGRATED_SYNTHESIS_CANDIDATE_READY
```

Integrated candidate chain proven in isolated `BTC_ML_DATA_ROOT`:

```text
feed → flow → localization → clusters → interaction
    → htf_structure → htf_ltf_context → auction_synthesis
```

---

## B. Stage 1 Health

| Check | Value |
| --- | --- |
| PID | `16607` (unchanged) |
| steps (live) | **21** |
| join | `EXACT_FRESH_MATCH` |

```text
Stage 1 healthy = true
```

---

## C. Current 21-Step Pipeline

Default `CANONICAL_PIPELINE` (live):

```text
00 candle_structure … 01 volume_localization … 07 volume_response …
09 auction_convergence 10 auction_synthesis … 20 mtf_availability
```

No Stage-2 producers registered in live default.

---

## D. Candidate 26-Step Pipeline

Builder: `canonical_pipeline_with_stage2_synthesis_inputs_candidate()`  
**Disabled by default** (not assigned to `CANONICAL_PIPELINE`).

Inserts before `auction_synthesis_engine_v1.py`:

```text
live_volume_flow_engine_v1.py
liquidity_cluster_engine_v1.py
flow_liquidity_interaction_engine_v3.py
htf_structure_engine_v1.py
htf_ltf_context_engine_v1.py
```

```text
candidate steps = 26 = 21 + 5
```

---

## E. Source-Proven Order

All required relative invariants enforced in builder asserts + hardening.

---

## F. Runtime Hardening

`validate_canonical_pipeline_order` accepts:

| Mode | Steps |
| --- | --- |
| legacy | 20 |
| Stage 1 live | 21 |
| Stage 2 integrated candidate | **26** |

No absolute indices. Negatives: missing/duplicate/out-of-order Stage-2 engines fail.

---

## G. Dependency Map

Added source-true deps for five producers (third production file — required for signature cycles):

| Engine | Dependencies |
| --- | --- |
| live_volume_flow | live_market_feed |
| liquidity_cluster | volume_localization_memory |
| flow_liquidity_interaction | flow + feed + clusters |
| htf_structure | live_market_feed |
| htf_ltf_context | flow + interaction + htf_structure |

`auction_synthesis` unchanged. Guard semantics unchanged.

---

## H. Production Files Changed

```text
1. src/btc_ml/runtime/pipeline.py
2. runtime_hardening.py
3. runtime_dependency_map.py
```

```text
production files changed = 3
engine algorithm changes = 0
```

---

## I. Path Provenance

| Artifact | Writer / Reader |
| --- | --- |
| live_volume_flow_memory | cognition via registry |
| liquidity_clusters_memory | cognition via registry |
| flow_liquidity_interaction_memory | cognition via registry |
| htf_structure_memory | diagnostics via registry |
| htf_ltf_context_memory | diagnostics via registry |
| auction_synthesis_memory | reinforcement via registry |

Candidate cycle resolved all inputs under isolated `stage2b11b_…` root.

---

## J. Legacy Fallback Protection

Repo-root May `liquidity_clusters_memory.parquet` left in place.  
Candidate cycle: **`legacy_consumed = 0`**, **`volume_localization_v2` not read**.

---

## K. Integrated Candidate Cycle

Cycle 1 (isolated): all five producers + synthesis **SUCCESS**.

| Engine | Tip / rows (cycle 1 family) |
| --- | --- |
| flow | tip `2026-07-26 16:45`, 3721 rows |
| clusters | 918 zones, current-price hits > 0 |
| interaction | matched 3720, non-neutral **1442** |
| htf_structure | tip `16:30` |
| htf_ltf_context | tip `16:30`, derived labels **48** |
| synthesis | SUCCESS (state-sparse OK) |

---

## L–Q. Outputs / Synthesis

| Gate | Value |
| --- | --- |
| flow tip > May 13 | true |
| clusters overlap market | true |
| non-neutral interaction | **1442** |
| HTF / context tips > May 13 | true |
| interaction-derived context | **48** |
| FAILED_EXPANSION | **9** |

---

## R. Dependency Signature Cycles

| Cycle | Result |
| --- | --- |
| 2 unchanged | all six engines **SKIP** |
| 3 + real held bar | cascade eligible; **false_skips = 0** |

Immediate post-bump: context correctly not eligible until upstream outputs refresh (not a false SKIP).

---

## S. Behavioral Comparison

Scenario B restores non-neutral interaction / derived context / `FAILED_EXPANSION=9` vs May-stale all-neutral interaction path. Algorithm unchanged — input freshness only.

---

## T. Tests

`tests/test_stage2b11b_integrated_synthesis_candidate.py` + related Stage 2B1.1A/A.2 + hardening suites.

---

## U. Deferred Issues

Unchanged algorithm issues remain deferred (dominant_behavior ties, neutral ambiguity, unused contextual_alignment, wall-clock synthesis tip).  
Activation must avoid `migrate_legacy` of May CWD clusters into cognition before first fresh write.

---

## V. Git Commit

```text
fix: prepare integrated inputs for auction synthesis
push = NOT PERFORMED
```

---

## W. Compliance

```text
restarts = 0
live writes = 0
default live pipeline = 21
push = NOT PERFORMED
```

---

## X. Next Step

```text
Этап 2B2 — controlled live activation of the integrated
flow + clusters + interaction + HTF + synthesis chain
```

Do **not** execute 2B2 here.
