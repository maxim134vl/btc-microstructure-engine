# Volume Localization Live-Wiring Candidate — Phase 4A

**Status:** `VOLUME_LOCALIZATION_LIVE_WIRING_CANDIDATE_READY`  
**Activation:** NOT performed  
**Algorithm:** `volume_localization_v1@8fbde36`

## A. Result

Production candidate prepared for:

```text
candle_structure_memory
→ volume_localization
→ volume_response
→ fresh localized_behavior
```

Bounded replay + tests green. Live pipeline not restarted. Live localization memory not rewritten by this phase. Flag `BTC_ML_VOLUME_LOCALIZATION_LIVE` defaults to `0`.

## B. Current Live Dataflow

| Step | Producer | Artifact | Consumer | Current status |
| ---- | -------- | -------- | -------- | -------------- |
| 1 | `candle_structure_engine_v1.py` | `candle_structure_memory.parquet` | volume localization | ACTIVE_FRESH (structure tip advances) |
| 2 | `volume_localization_engine_v1.py` | `volume_localization_memory.parquet` | volume response | SOURCE restored; REGISTERED_NOT_RUNNING (not in live `CANONICAL_PIPELINE`) |
| 3 | `volume_response_engine_v1.py` | `volume_response_state.parquet` | reinforcement / probabilistic | ACTIVE; reads v2 tip-carry while flag OFF (`ACTIVE_STALE` localization dependency) |
| 4 | volume response | `localized_behavior` | reinforcement / probabilistic | CONSUMER_FALLBACK (stale v2 tip-carry) |

Proven order for activation (candidate helper only):

```text
candle_structure → volume_localization → … → volume_response
```

## C. Orphan Artifact Analysis

| Path | Tip | Rows | Role |
| ---- | --- | ---: | ---- |
| `data/cognition/volume_localization_memory.parquet` | 2026-07-10T05:45:00Z | 5000 | Intended production v1 artifact (orphan; schema has ELV/concentration/zones/`behavior`) |
| `data/cognition/volume_localization_v2_memory.parquet` | 2026-05-13T12:45:00Z | 1064 | Current live response dependency (stale tip-carry) |
| `volume_localization_memory_v2.parquet` / `volume_localization_state.parquet` | — | — | Not used as production target |

**Intended production output path:** `data/cognition/volume_localization_memory.parquet`

## D. Production Module Restoration

- Restored proven formulas from git `8fbde36` into `src/btc_ml/cognition/volume_localization_engine_v1.py`
- Root shim `volume_localization_engine_v1.py` for pipeline-style entry
- Atomic write via `parquet_utils.atomic_parquet_write`
- No inventory transfer; no location_bias derivation
- Aliases: `localized_behavior`←`behavior`, `zone_lower`←`zone_low`, `zone_upper`←`zone_high`

## E. Runtime Registration Candidate

- Live `CANONICAL_PIPELINE` unchanged (still 20 steps; localization absent)
- Candidate helper: `canonical_pipeline_with_volume_localization_candidate()` inserts after `candle_structure_engine_v1.py`, before `volume_response_engine_v1.py`
- `engine_registry.py` / dependency map not required for this candidate

## F. Dependency / Freshness Contract

When flag ON (activation phase only):

- Exact timestamp join structure ↔ localization
- Only `EXACT_FRESH_MATCH` supplies ELV/concentration/behavior
- Missing / stale / ambiguous → null fields + explicit status (never 0 / never `"neutral"`)

Default flag OFF preserves legacy v2 tip-carry.

## G. Exact Join Contract

Join key: `timestamp` (M15 bar open).  
Forbidden: nearest, ffill/bfill, ±N window, stale carry-forward.

Statuses: `EXACT_FRESH_MATCH` | `NO_LOCALIZATION_MATCH` | `AMBIGUOUS_LOCALIZATION_MATCH` | `STALE_LOCALIZATION_MATCH`

## H. Localized Behavior Mapping

Identity mapping (proven):

```text
localization.behavior → volume_response.localized_behavior
```

Labels produced by v1@8fbde36:

- `body_participation`
- `localized_absorption`
- `localized_distribution`

`rejection_without_resolution` is not emitted by this algorithm (not introduced).

## I. 5000-Row Production Parity

Against legacy orphan full timestamp overlap:

| Metric | Value |
| ------ | ----- |
| rows_compared | 5000 |
| numeric parity | 100% (max abs error 0) |
| categorical parity | 100% |
| vs shadow (256 overlap) | 100% |

Candidate artifacts under `data/candidate/volume_localization_live_wiring/`.

## J. Volume Response Before/After

Live response timestamps are wall-clock (not bar open) → exact timestamp overlap with candidate projection = 0 (fuzzy join forbidden).

| Field | Expected change on activation | Flag OFF now |
| ----- | ---------------------------- | ------------ |
| estimated_local_volume | yes | tip-carry from v2 (unchanged path) |
| volume_concentration | yes | tip-carry from v2 |
| localized_behavior | yes | tip-carry from v2 |
| effort_result_state / volume_event / unfinished_auction | no | not rewritten by candidate |

Tip-level research contrast (stale live vs fresh candidate tip):

- live `localized_behavior`: `localized_distribution` (stale tip-carry)
- candidate tip: `localized_absorption` with fresh ELV

## K. Downstream Counterfactual

Reinforcement / probabilistic already read `volume_response.localized_behavior`.  
No weight/formula changes. Research tip delta: distribution bonus −0.1 if tip becomes absorption vs stale distribution.

## L. Final Context Counterfactual

Candidate does not rewrite final context. Overlap observational only; directional LONG/SHORT/OBSERVE changes = 0 by construction.

## M. Tests

```bash
pytest -q \
  tests/test_volume_localization_live_wiring_candidate.py \
  tests/test_volume_localization_shadow_restoration.py \
  tests/test_capability_gap_phase1.py \
  tests/test_candle_structure_parquet_atomicity.py \
  tests/test_context_refresh_daemon_scheduler.py \
  tests/test_decision_lineage_passthrough.py \
  tests/test_architecture_restoration_phase2.py \
  tests/test_canonical_validation_plane.py
```

Result: green.

## N. Production Files Changed (≤4)

1. `src/btc_ml/cognition/volume_localization_engine_v1.py`
2. `volume_localization_engine_v1.py`
3. `volume_response_engine_v1.py`
4. `src/btc_ml/runtime/pipeline.py`

Plus tests + this audit + research runner (non-production).

## O. Live Data Writes

Candidate runner writes only under `data/candidate/volume_localization_live_wiring/`.  
Localization engine `run(write=True)` was not executed against live path in this phase.  
`live_data_writes` from this phase = **0**.

## P. Process Restarts

**0** — feed / pipeline / refreshers / manager / traders / OPS / Vite left running.

## Q. Commit

Selective commit message:

```text
feat: prepare canonical volume localization live wiring
```

## R. Push

NOT PERFORMED

## S. Recommended Controlled Activation (future)

Do **not** activate in this phase. Separate controlled steps:

1. Register `volume_localization_engine_v1.py` into live `CANONICAL_PIPELINE` via candidate helper order
2. Set `BTC_ML_VOLUME_LOCALIZATION_LIVE=1` for volume_response
3. Coordinated restart of cognition pipeline only (not manager/traders)
4. Verify freshness: localization tip == candle_structure tip; response join `EXACT_FRESH_MATCH`
5. Watch reinforcement/probabilistic for expected fresh `localized_behavior` influence — without formula edits
