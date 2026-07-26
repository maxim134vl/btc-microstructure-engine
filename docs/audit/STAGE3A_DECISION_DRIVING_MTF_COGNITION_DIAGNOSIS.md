# Stage 3A — Decision-Driving MTF Cognition Diagnosis

**Status:** `STAGE3A_MTF_ROOT_CAUSE_PROVEN`  
**Date (UTC):** 2026-07-26  
**HEAD:** `713ef3b` (`memory/canonical-system`)  
**Live pipeline:** PID `61126`, 26 steps  
**Candidate evidence:** `data/candidate/architecture_recovery/stage3a_mtf_cognition_diagnosis/`

Compliance: production source changes = 0 · process restarts = 0 · live writes = 0 · commit/push = NOT PERFORMED.

---

## A. Result

Fresh `auction_synthesis` **does not** and **cannot** refresh decision-driving multi-timeframe cognition under the current source contract.

| Finding | Proof |
| --- | --- |
| Decision-driving MTF artifact | `data/cognition/multi_timeframe_synthesis.parquet` |
| Producer | `stage2_cognition_runtime_v1.py` (pipeline step after `auction_synthesis`) |
| Reads `auction_synthesis`? | **No** — only `STATE["candle_structure"]` / `candle_structure_memory.parquet` |
| Tip | **2026-07-25 08:45:00Z** (167 climax-derived rows) |
| Candle tip | **2026-07-26 18:30:00Z** → **~33.75h lag** |
| Engine executing? | **Yes** — ~241 `STAGE 2 COGNITION RUNTIME` / `SYNTHESIS ROWS` after Stage 2B2 activation; mtime advances |
| Why tip unchanged | Climax filter keeps only non-`NORMAL` events; **0** new M15 climax events after 2026-07-25 08:45 |

**Root cause class:** `MULTIPLE_BLOCKERS`

1. **Architectural disconnect (primary for “synthesis restore didn’t help”):** restored `auction_synthesis` is not an input to the decision-driving MTF producer.  
2. **Event-sparse climax tip (primary for tip lag vs candle):** producer runs on fresh candle_structure, rewrites the same climax event set ending 2026-07-25 08:45.

---

## B. Stage 1–2 Health

| Check | Status |
| --- | --- |
| Pipeline PID 61126, count=1, steps=26 | PASS |
| Flags: persistent_worker, localization=1, stage2_inputs=1 | PASS |
| `localization_join_status` | `EXACT_FRESH_MATCH` |
| candle / localization / flow / interaction tips | fresh (flow through 18:30) |
| clusters current-price hits | 8 |
| interaction non-neutral | ~1437 |
| HTF structure/context | fresh (1-bar lag deferred) |
| auction_synthesis evaluates on fresh HTF | PASS (wall-clock tip 18:30:40Z; event-sparse persist) |
| Post–Stage 2 gate natural bars in flow | 18:00 / 18:15 / 18:30 present |

No `STAGE3A_UPSTREAM_REGRESSION`.

---

## C. MTF Implementations Inventory

| Module | Role | Pipeline | Registry | Output |
| --- | --- | --- | --- | --- |
| `stage2_cognition_runtime_v1.py` | **Decision-driving MTF producer** | yes (after auction_synthesis) | yes | `multi_timeframe_synthesis.parquet`, `runtime_cognition_memory.parquet` |
| `multi_timeframe_synthesis_engine.py` | Library (synthesize_*) | no | no | used by stage2 |
| `multi_timeframe_dataset_builder.py` | Library (TF aggregate) | no | no | used by stage2 |
| `auction_climax_engine_v1.py` | Library (climax events) | no | no | used by stage2 |
| `mtf_availability_runtime_engine_v1.py` | Availability read-model | yes (last step) | yes | `multi_timeframe_availability_memory.parquet` + latest JSON |
| `runtime_multi_timeframe_availability.py` / `multi_timeframe_availability.py` | Availability helpers | via mtf_availability | — | — |
| `runtime_cognition_engine_v1.py` | Loads MTF+cognition into STATE; alignment enrich | yes | **not in ENGINES** (subprocess fallback) | no tip writer (reads only) |
| `intermediate_cognition_engine_v1.py` | Intermediate layer over candles + runtime_cognition | yes | yes | `intermediate_cognition_memory.parquet` |
| `multi_timeframe_auction_engine_v1.py` | Legacy/research | no | no | not live decision path |

---

## D. Availability vs Decision-Driving MTF

| Layer | Producer | Artifact | Live/Research | Consumer | Decision-driving |
| --- | --- | --- | --- | --- | ---: |
| A. Availability | `mtf_availability_runtime_engine_v1` | `multi_timeframe_availability_memory.parquet` (+ latest JSON) | Live read-model | `timeframe_state_adapter`, OPS | **no** (`trading_use_forbidden`) |
| B. Analytical climax→MTF | `stage2_cognition_runtime_v1` + climax/synth libs | `multi_timeframe_synthesis.parquet` | Live | runtime cognition, manager adapter | **yes** |
| C. Runtime cognition projection | `stage2` write + `runtime_cognition_engine_v1` load | `runtime_cognition_memory.parquet` | Live | arbitration, intermediate | **yes** (same tip as B) |

Availability is fresh (M15 `FRESH_EVENT`; D1 `TIMEFRAME_NOT_LIVE` / `NO_LIVE_STAGE2_WRITER` only). Fresh availability ≠ fresh decision MTF tip.

---

## E. Decision-Driving Artifact

| Field | Value |
| --- | --- |
| Path | `data/cognition/multi_timeframe_synthesis.parquet` |
| Rows | 167 |
| Tip | 2026-07-25 08:45:00+00:00 |
| First | 2026-05-02 14:30:00+00:00 |
| mtime | advances with every stage2 SUCCESS (~18:55Z observed) |
| Schema (core) | `timestamp`, `synthesis_state`, `trigger_event`, `persistence`, `persistence_score`, `structural_rank`, `alignment_score`, `location_bias` (+ lineage) |
| Primary key | climax event `timestamp` (sparse) |
| Timestamp semantics | M15 climax event time (bar identity of detected event) |
| Persistence | Full rewrite of event set each run (`atomic_parquet_write`) |
| Producer | `stage2_cognition_runtime_v1.py` L108–124 |
| Direct consumers | `runtime_cognition_engine_v1.py` L37; `timeframe_state_adapter.py` L34/L287–300; stage2 also exports `runtime_cognition_memory` |

Priority: `multi_timeframe_synthesis` is authoritative for MTF decision fields; `runtime_cognition_memory` is the column-filtered export of the same tip.

---

## F. MTF Producer Contract

**File:** `stage2_cognition_runtime_v1.py`  
**Entrypoint:** `run()` L94–168  
**Build:** `build_stage2_synthesis()` L28–73 → climax ×4 TF → `synthesize_multi_timeframe_behavior`

| Input | Producer | Required | Join/fetch | Current tip |
| --- | ---: | ---: | --- | --- |
| `candle_structure_memory.parquet` via `STATE["candle_structure"]` | candle_structure engine | yes | full frame | 2026-07-26 18:30 |

**Not read (confirmed absent from source):**  
`auction_synthesis_memory`, `auction_convergence`, `htf_structure`, `htf_ltf_context`, `volume_response`, `flow`, `clusters`, `interaction`, availability memory.

Dependency map entry: only `candle_structure_memory.parquet` — **matches source**.

---

## G. Actual Inputs

Sole production input: candle structure behavioral/OHLCV frame used by `process_auction_climax` → non-`NORMAL` `auction_event_type` rows → MTF synthesis rows.

---

## H. Auction Synthesis Consumption

```text
MTF producer reads auction_synthesis = no
```

Architecturally, auction synthesis is a **parallel Stage-2 reinforcement/state** artifact (`auction_synthesis_engine_v1`, deps: volume_response + HTF). Decision MTF is a **separate climax-aggregation path**. Restoring synthesis refreshes reinforcement/probabilistic consumers, not `multi_timeframe_synthesis` tip.

---

## I. Pipeline / Runtime Status

| Engine | Registered | Step (26-mode) | Post-activation (log) |
| --- | --- | --- | --- |
| `auction_synthesis_engine_v1` | via subprocess/engines | before stage2 | mostly SKIPPED (`DEPENDENCY_SIGNATURE_UNCHANGED`); SUCCESS on changed deps |
| `stage2_cognition_runtime_v1` | yes | after synthesis | ~241 RUNNING with body+`SYNTHESIS ROWS`; ~1 SKIP |
| `runtime_cognition_engine_v1` | **no ENGINES entry** | after stage2 | ~242 RUNNING (subprocess) |
| `mtf_availability_runtime_engine_v1` | yes | last | SUCCESS nearly every cycle |

Unknown skip reasons for decision MTF: **0** (skips are dependency-signature; stage2 almost never skip).

---

## J. Dependency Map and Guard

| Dependency | Read by source | In map | Correct |
| --- | ---: | ---: | ---: |
| candle_structure_memory | yes | yes | yes |
| auction_synthesis_memory | no | no | N/A (not used) |
| multi_timeframe_synthesis (self) | write only | no | OK |

`runtime_cognition_engine_v1` map lists `runtime_cognition_memory.parquet` only — source also reads `multi_timeframe_synthesis.parquet` (**map incomplete** for runtime cognition, not the MTF tip blocker).

Event-sparse auction_synthesis mtime stalls do **not** block stage2 (stage2 does not depend on it). Stage2 runs when candle_structure mtime changes.

---

## K. Event-Sparse Compatibility

| Path | Classification |
| --- | --- |
| Climax→MTF tip | **event-sparse compatible** — engine executes, consumes fresh candles, tip = last climax event |
| Auction synthesis → MTF | **not applicable** — not an input |
| Expectation “new synthesis row every M15 ⇒ new MTF row” | **false** under current source |

Proven: post-activation stage2 executions rewrite 167 rows with identical tip `2026-07-25 08:45`.

---

## L. Timestamp Compatibility

| Artifact | Semantics |
| --- | --- |
| candle_structure | M15 bar timestamp |
| climax / MTF / runtime_cognition | climax event bar timestamp (sparse) |
| auction_synthesis | wall-clock evaluation time (deferred identity issue) |
| HTF | bar tip with 1-bar lag (deferred) |
| availability | evaluation_timestamp / source_bar_close |

Joins: MTF synthesis uses windowed timeframe alignment on climax events (`multi_timeframe_synthesis_engine.py`); runtime cognition uses `iloc[-1]` of cognition + merge on timestamp for alignment; arbitration uses asof from cognition_mem; manager adapter uses last synthesis row with `timestamp <= source_bar_close`.

Conflict: **fresh every-bar candle vs sparse climax tip** → consumers see ~34h stale decision tip while market bars advance.

---

## M. Artifact Inventory

See `data/candidate/.../artifact_inventory.json`.

| Artifact | Tip / note |
| --- | --- |
| multi_timeframe_synthesis | 2026-07-25 08:45 · 167 rows · mtime live |
| runtime_cognition_memory | same tip · 167 rows · mtime live |
| multi_timeframe_availability_memory | evaluation 2026-07-26 18:45 · fresh |
| intermediate_cognition_memory | 2026-07-26 16:15 · 520 rows |
| auction_synthesis_memory | wall-clock 2026-07-26 18:30:40 |
| market_context_lifecycle_memory | **2026-07-26 18:30** (fresh; not registry-named the same way) |
| runtime_cognition_composite | **missing** |

---

## N. Runtime Cognition Contract

| Field | Value |
| --- | --- |
| Writer of memory tip | `stage2_cognition_runtime_v1` (export columns) |
| Loader | `runtime_cognition_engine_v1.run` L28–137 |
| Reads | `runtime_cognition_memory.parquet`, `multi_timeframe_synthesis.parquet` via `safe_read_parquet` |
| Behavior | enrich alignment; put latest row into `STATE["runtime_cognition"]`; does not advance tip |
| Tip | 2026-07-25 08:45 |
| Alignment audit file | registered but absent on disk at diagnosis time |

---

## O. Context Consumer Contract

| Consumer | Read | On stale/missing |
| --- | --- | --- |
| `auction_context_arbitration_engine_v1` | prefers `runtime_cognition_composite` (missing) → falls back to `runtime_cognition_memory` asof `trigger_event` / `location_bias` | OBSERVE paths when cognition fields empty |
| `timeframe_state_adapter` | availability + lifecycle + **multi_timeframe_synthesis** | `NO_ACTION` from availability statuses; synthesis metadata from last eligible synthesis row ≤ bar close |
| lifecycle memory | advances with candle tip (18:30) | independent of MTF tip |

First decision-metadata stale link for manager/trading adapters: **synthesis tip 2026-07-25** while lifecycle/availability already on 2026-07-26.

---

## P. End-to-End Lineage

| Producer | Artifact | Tip | Consumer | Read path | Status |
| --- | --- | --- | --- | --- | --- |
| auction_synthesis_engine | auction_synthesis_memory | 2026-07-26 18:30 wall | probabilistic / reinforcement | resolve paths | fresh (parallel) |
| *(no edge)* | — | — | stage2_cognition | — | **broken expectation** |
| candle_structure | candle_structure_memory | 2026-07-26 18:30 | stage2_cognition | STATE/safe_read | fresh |
| stage2_cognition | multi_timeframe_synthesis | **2026-07-25 08:45** | runtime_cognition / adapter | safe_read / explicit cognition path | **STALE tip** |
| stage2_cognition | runtime_cognition_memory | **2026-07-25 08:45** | arbitration / intermediate | safe_read | **STALE tip** |
| runtime_cognition engine | STATE only | same | in-process consumers | STATE | projects stale tip |
| lifecycle writer | market_context_lifecycle_memory | 2026-07-26 18:30 | manager adapter | explicit path | fresh |
| mtf_availability | availability memory | 2026-07-26 18:45 eval | manager adapter | explicit path | fresh |

**First stale/missing link:**  
`fresh candle_structure → stage2 executes → climax yields no new events → multi_timeframe_synthesis / runtime_cognition tip frozen at 2026-07-25 08:45`.

Parallel restored `auction_synthesis` never enters this edge.

---

## Q. Last ~500 Runtime Cycles (post-activation log window)

Log-count method (more reliable than block parser for long stage2 bodies):

| Engine | SUCCESS-like | SKIPPED | Notes |
| --- | ---: | ---: | --- |
| stage2_cognition | ~241 bodies with `SYNTHESIS ROWS` | ~1 | executes; tip unchanged |
| runtime_cognition | ~242 RUNNING | ~1 | loads stale tip |
| intermediate | ~SUCCESS majority | low | tip 16:15 (separate) |
| auction_synthesis | minority SUCCESS | majority `DEPENDENCY_SIGNATURE_UNCHANGED` | expected event-sparse/deps |
| mtf_availability | ~almost all SUCCESS | 0 | fresh availability |
| auction_context_arbitration | ~almost all SUCCESS | 0 | runs on fallback cognition |

| Engine | Skip reason | Count | Blocking input |
| --- | --- | ---: | --- |
| auction_synthesis | DEPENDENCY_SIGNATURE_UNCHANGED | majority | unchanged response/HTF mtimes between bars |
| stage2_cognition | DEPENDENCY_SIGNATURE_UNCHANGED | ~1 | candle mtime unchanged |

Unknown skip reasons: **0**.

---

## R. Before / After Stage 2 Activation

| Layer | Before (pre–61126 / May–stale HTF era) | After PID 61126 |
| --- | --- | --- |
| auction_synthesis inputs | May HTF → weak/stale semantics | fresh HTF/context; evaluates |
| auction_synthesis tip | wall-clock sparse | still sparse; post-act states observed |
| multi_timeframe_synthesis tip | 2026-07-25 08:45 | **unchanged** 2026-07-25 08:45 |
| runtime_cognition tip | same | **unchanged** |
| stage2 SUCCESS | was running | still running (~241) |
| availability | fresh | fresh |

**Conclusion:** restoring auction synthesis **did not** revive decision-driving MTF tip.

---

## S. Diagnostic Replay

Directory: `data/candidate/architecture_recovery/stage3a_mtf_cognition_diagnosis/`

| Scenario | Result |
| --- | --- |
| A — current production candle_structure | 6996 candles → 167 climax events → 167 MTF rows; tip 2026-07-25 08:45; **100% categorical parity**, alignment max error **0** vs live |
| B — fresh Stage 2 lineage (flow/HTF/auction_synthesis) | **No effect** — producer source does not read those artifacts |
| C — auction_synthesis state carry | **N/A** — not in contract; climax path already event-sparse-compatible |

Minimal change that would unblock tip freshness (research conclusion, not implemented): either (i) new climax events under existing formulas, or (ii) Stage 3B wiring so a fresher decision artifact (e.g. auction_synthesis / HTF context) feeds consumers — **without** claiming climax formula changes.

---

## T. Root Cause

```text
MULTIPLE_BLOCKERS
```

### Blocker 1 — Restored auction_synthesis not consumed by decision MTF

- **Condition:** `stage2_cognition_runtime_v1.run` only uses `STATE["candle_structure"]` (L99–108); no `auction_synthesis` reader  
- **Files/lines:** `stage2_cognition_runtime_v1.py` L94–124; `runtime_dependency_map.py` stage2 deps  
- **Affected:** all cycles after Stage 2B2 — synthesis restore orthogonal to MTF tip  
- **Replay:** Scenario B unused-inputs proof  

### Blocker 2 — Climax event tip frozen (event-sparse, engine alive)

- **Condition:** `auction_climax_engine_v1` returns `auction_event_type != NORMAL` only; last M15 event 2026-07-25 08:45; 0 events after  
- **Files/lines:** `auction_climax_engine_v1.py` L649–656; `multi_timeframe_synthesis_engine.py` iterates m15_states  
- **Affected:** tip lag ~33.75h vs candle; consumers inherit stale decision metadata  
- **Replay:** Scenario A identical tip/rows; stage2 log SUCCESS with unchanged tip  

Not a false dependency skip of stage2. Not availability-layer failure.

---

## U. Minimal Stage 3B Scope

Do **not** change climax/MTF formulas unless a separate contract-drift stage proves it.

Recommended production touch set (**≤3**):

| File | Exact defect | Why required |
| --- | --- | --- |
| `stage2_cognition_runtime_v1.py` | Decision MTF isolated from restored auction/HTF Stage-2 chain | Only producer of decision-driving `multi_timeframe_synthesis` / `runtime_cognition_memory` |
| `runtime_dependency_map.py` | stage2 deps = candle only; runtime_cognition map omits synthesis read | Guard/map must match any new reads |
| `engine_registry.py` *(optional hygiene)* | `runtime_cognition_engine_v1` missing from `ENGINES` | Ensures in-process contract parity (not tip root cause) |

If Stage 3B requires redesigning climax thresholds/labels to force every-bar MTF rows → **out of minimal scope** (`STAGE3A_SCOPE_TOO_LARGE` for formula work). Prefer wiring/state-carry or consumer input selection over formula edits.

---

## V. Deferred Issues

Update `docs/audit/DEFERRED_ISSUES_REGISTER.md`:

- Mark auction_synthesis “stale HTF” entry as superseded by live Stage 2B2  
- Add Stage 3A blockers (synthesis↔MTF disconnect; climax tip lag)  
- Do not fix HTF lag, dual PID, dominant_behavior, etc.

---

## W. Compliance

```text
production changes = 0
test changes = 0
pipeline/hardening/dependency-map changes = 0
process restarts = 0
live parquet writes = 0
commit = NOT PERFORMED
push = NOT PERFORMED
```

---

## X. Next Step

**Этап 3B — минимальное восстановление decision-driving MTF cognition** (не выполнять в 3A).
