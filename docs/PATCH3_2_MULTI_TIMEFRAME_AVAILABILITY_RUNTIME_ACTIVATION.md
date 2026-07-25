# PATCH 3.2 — Multi-Timeframe Availability Runtime Activation

**Tag:** `20260724_170055`  
**Branch:** `memory/canonical-system`  
**Mode:** production operational read-model (no trading semantic changes)

---

## A. Result

```text
PATCH3_MTF_AVAILABILITY_RUNTIME_ACTIVATED
```

Canonical MTF availability history + latest snapshot are live, written by the pipeline post-cycle stage. D1 is explicitly `TIMEFRAME_NOT_LIVE`. Context / lifecycle / decision / paper consumers unchanged.

---

## B. Production Ownership

| Field | Value |
| --- | --- |
| Owner class | `PIPELINE_POST_CYCLE_READ_MODEL` |
| Writer | `mtf_availability_runtime_engine_v1.py` |
| Stage class | `REQUIRED_OPERATIONAL_READ_MODEL` |
| Integration | last step of `CANONICAL_PIPELINE` (step 20) |
| New daemon | none |

Availability does not own MTF source datasets, does not start pipeline/context/paper, and does not invent missing source events.

---

## C. Runtime Paths

| Artifact | Path |
| --- | --- |
| Append-only history | `data/cognition/multi_timeframe_availability_memory.parquet` |
| Latest snapshot | `data/runtime/multi_timeframe_availability_latest.json` |
| Status sidecar | `data/runtime/multi_timeframe_availability_status.json` |
| History metadata | `data/cognition/multi_timeframe_availability_memory.parquet.meta.json` |
| Contract | `config/multi_timeframe_availability_contract.json` |
| Canonical helper | `multi_timeframe_availability.py` |
| Runtime writer | `runtime_multi_timeframe_availability.py` |
| Research shim | `scripts/research/multi_timeframe_availability.py` |

---

## D. Live Timeframe Support

| TF | Support | Runtime status contract |
| --- | --- | --- |
| M15 | `LIVE_SUPPORTED` | dense authoritative as-of |
| M30 | `LIVE_SUPPORTED` | last confirmed between closes |
| H1 | `LIVE_SUPPORTED` | last confirmed between closes |
| H4 | `LIVE_SUPPORTED` | last confirmed between closes |
| D1 | `RESEARCH_ONLY_NOT_LIVE` | `TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER` / `NOT_IMPLEMENTED_LIVE` |

D1 research/dashboard state is never promoted into live availability.

---

## E. Pipeline Integration

```text
... → adaptive_meta_cognition_engine_v1.py
    → mtf_availability_runtime_engine_v1.py
```

- Evaluation anchor = latest safe completed M15 close (`open_tip + 15m`)
- PIT: `source_bar_close <= evaluation_timestamp`
- Append-only missing evaluation sets (5 rows: M15/M30/H1/H4/D1)
- Existing history prefix always wins
- Fail-closed: previous artifacts retained; upstream cognition not rolled back
- No-op log: `MTF_AVAILABILITY_NO_NEW_EVALUATION`

Observed in `logs/runtime_stack/runtime.log` after restart.

---

## F. Initial Activation

| Gate | Result |
| --- | --- |
| Candidate rebuild equality (exact Patch 3.1 anchors) | `UNEXPLAINED=0` |
| `future_joins` | 0 |
| `unclosed_bar_joins` | 0 |
| `duplicate_source_keys` | 0 |
| Bootstrap history | 96 evaluations × 5 = 480 rows |
| Previous production state | `NOT_PRESENT` |

Artifacts:

- `data/research/patch3_2_candidate_comparison.json`
- `data/research/patch3_2_backup_manifest_20260724_170055.json`
- `data/research/patch3_2_production_backups_20260724_170055/`

---

## G. Live Cycles

Captured natural evaluations:

| Evaluation | Rows added | M15 | M30 | H1 | H4 | D1 |
| --- | ---: | --- | --- | --- | --- | --- |
| 2026-07-24T17:15:00Z | 5 | FRESH_EVENT / close 17:15 / new | AVAILABLE_LAST_CONFIRMED / close 17:00 | AVAILABLE_LAST_CONFIRMED / close 17:00 | AVAILABLE_LAST_CONFIRMED / close 16:00 | TIMEFRAME_NOT_LIVE |
| 2026-07-24T17:30:00Z | pipeline-advanced | FRESH_EVENT / close 17:30 / new | FRESH_EVENT / close 17:30 / new | AVAILABLE_LAST_CONFIRMED / close 17:00 | AVAILABLE_LAST_CONFIRMED / close 16:00 | TIMEFRAME_NOT_LIVE |

Artifact: `data/research/patch3_2_live_cycles_20260724_170055.json`

---

## H. No-op

Repeated cycles on the same safe evaluation:

- history rows unchanged
- history sha unchanged
- event `MTF_AVAILABILITY_NO_NEW_EVALUATION`
- no duplicate evaluation×timeframe keys

Artifact: `data/research/patch3_2_noop_20260724_170055.json`

---

## I. Restart

Bounded `run.py`-only restart:

| Check | Result |
| --- | --- |
| Pipeline PID | `10952 → 20041` |
| Context refresher PID | `97695` unchanged |
| Paper PID | `79502` unchanged |
| History not rebuilt from scratch | true (append-only tip growth only) |
| Zombie old PID | none |

Artifact: `data/research/patch3_2_restart_20260724_170055.json`

---

## J. No-Look-Ahead

| Gate | Value |
| --- | ---: |
| future_joins | 0 |
| unclosed_bar_joins | 0 |
| duplicate_source_keys | 0 |
| duplicate_evaluation_timeframe_keys | 0 |

Artifact: `data/research/patch3_2_no_lookahead.csv`

---

## K. Runtime Health

Latest snapshot overall:

```text
HEALTHY_WITH_UNSUPPORTED_TIMEFRAME
```

Example tip (`2026-07-24T17:30:00Z`):

```text
M15: FRESH_EVENT
M30: FRESH_EVENT
H1:  AVAILABLE_LAST_CONFIRMED
H4:  AVAILABLE_LAST_CONFIRMED
D1:  TIMEFRAME_NOT_LIVE (NO_LIVE_STAGE2_WRITER)
```

D1 unsupported does not mark the availability dataset BROKEN.

---

## L. Consumer Isolation

Static check: context / lifecycle / decision / paper modules do **not** import or read:

- `runtime_multi_timeframe_availability`
- `multi_timeframe_availability_memory`
- `mtf_availability_runtime_engine_v1`

Allowed consumers: runtime health / ops reports / future Patch 4 dashboard only.

---

## M. Preservation

Pre/post activation historical equality:

| Plane | Historical changes |
| --- | ---: |
| final context / lifecycle | 0 |
| decision | 0 |
| paper signals/orders/trades/positions | 0 |

Artifact: `data/research/patch3_2_preservation_20260724_170055.json`

Natural tip growth from live system remains allowed and is not attributed to availability.

---

## N. Tests

- `tests/test_patch3_1_multi_timeframe_availability.py`
- `tests/test_patch3_2_mtf_availability_runtime.py` (33 acceptance checks covering helper share, live TFs, D1 not live, PIT, atomicity, append-only, noop, consumer isolation, flags)

---

## O. Safety

- no trading semantic changes
- no execution / exchange
- `BTC_ML_CONTINUATION_PROGRESSION=0`
- `PRICE_GATE=OFF`
- paper remains `--skip-refresh`
- no Patch 4 / Patch 5
- no commit / push

---

## P. Next Step

After:

```text
PATCH3_MTF_AVAILABILITY_RUNTIME_ACTIVATED
```

next stage (not started here):

```text
PATCH 4 — OPS DASHBOARD RUNTIME TRUTH AND PARITY
```
