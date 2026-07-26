# Volume Response Canonical Timestamp Identity — Phase 4B

**Status:** `VOLUME_RESPONSE_TIMESTAMP_IDENTITY_CANDIDATE_READY`  
**Activation:** NOT performed  
**Depends on:** Phase 4A commit `33e0826`

## A. Result

Canonical candle identity candidate prepared. Exact localization join no longer depends on wall-clock equality.

## B. Current Timestamp Semantics

| Field | Meaning | Producer | Current format |
| ----- | ------- | -------- | -------------- |
| `volume_localization.timestamp` | M15 bar open | localization engine | bar-aligned UTC |
| `volume_response.timestamp` | wall-clock evaluation | `datetime.utcnow()` | non-bar wall-clock |
| `source_candle_timestamp` | *(absent in live)* | — | — |
| `evaluated_at` | *(absent in live)* | — | — |
| `candle_structure.timestamp` | M15 bar open | candle structure | bar-aligned UTC |

No hidden bar-open field existed on live `volume_response_state`.

## C. Root Cause of Zero Exact Overlap

```text
localization.timestamp = bar open
volume_response.timestamp = process wall-clock (datetime.utcnow())
→ exact overlap = 0
```

Join at compute time already used `latest_structure["timestamp"]`; persisted response key did not.

## D. Canonical Timestamp Contract (additive)

```text
source_candle_timestamp = candle_structure.timestamp   # passthrough
source_candle_close     = source_candle_timestamp + 15m
evaluated_at            = wall-clock calculation time
timestamp               = legacy wall-clock (unchanged meaning)
```

Join when `BTC_ML_VOLUME_LOCALIZATION_LIVE=1`:

```text
volume_response.source_candle_timestamp == volume_localization.timestamp
```

Legacy rows without source field → `LEGACY_RESPONSE_NO_SOURCE_TIMESTAMP` (no synthetic fill).

Identity fields persist only when live flag is ON (no live schema writes while inactive).

## E. Production Files Changed (≤3)

1. `volume_response_engine_v1.py`
2. `src/btc_ml/cognition/volume_response_timestamp_identity.py`

(+ tests, research runner, this audit)

## F. Exact Join Coverage

Candidate-generated rows (5000):

| Status | Count |
| ------ | ----: |
| EXACT_FRESH_MATCH | 5000 |
| NO_LOCALIZATION_MATCH | 0 |
| AMBIGUOUS | 0 |
| STALE | 0 |

Share = **100%**

## G. 5000-Row Replay

Artifacts under `data/candidate/volume_localization_timestamp_identity/`:

- `volume_response_candidate.parquet`
- `timestamp_identity_comparison.parquet`
- `join_coverage_report.json`
- `candidate_status.json`

ELV / concentration / behavior parity = **100%**

## H. Three Natural-Candle Simulation

| Bar | Join | Wall-clock == source |
| --- | ---- | -------------------- |
| 2026-07-26T09:00:00Z | EXACT_FRESH_MATCH | false |
| 2026-07-26T09:15:00Z | EXACT_FRESH_MATCH | false |
| 2026-07-26T09:30:00Z | EXACT_FRESH_MATCH | false |

## I. Behavioral Equality

Allowed deltas: identity fields + fresh localization fields under flag ON.  
Unrelated effort/result / unfinished / classifications untouched. Formulas unchanged.

## J. Legacy Compatibility

Live response sample (200): all `LEGACY_RESPONSE_NO_SOURCE_TIMESTAMP`.  
No backfill. No synthetic source timestamps.

## K. Tests

`tests/test_volume_response_canonical_timestamp_identity.py` + required suite — green.

## L. Live Writes

**0**

## M. Process Restarts

**0**

## N. Commit

Selective: `fix: preserve canonical candle identity in volume response`

## O. Push

NOT PERFORMED

## P. Recommended Activation

After this + `33e0826`:

1. Register localization in live pipeline (candidate order)
2. Set `BTC_ML_VOLUME_LOCALIZATION_LIVE=1`
3. Restart cognition pipeline only
4. Verify new response rows carry `source_candle_timestamp` and `EXACT_FRESH_MATCH`
