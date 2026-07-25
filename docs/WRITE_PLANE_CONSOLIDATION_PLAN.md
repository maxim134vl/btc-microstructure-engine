# Write-Plane Consolidation Plan

Candidate-only consolidation of fragmented runtime truth planes.  
**No production code/data changes, restarts, flag flips, trading changes, or commit/push.**

Generated: 2026-07-24T10:48:18Z via `scripts/research/run_write_plane_consolidation_audit.py`  
Frozen: `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`, execution disabled.

---

## A. Three Write-Planes

| Plane | Writer | Outputs | Cadence | Consumers | Current authority |
| --- | --- | --- | --- | --- | --- |
| **canonical_pipeline_loop** | `run.py` → `src/btc_ml/runtime/pipeline.py` (19 engines); PID **20908** active | `data/cognition/*` sensory/belief, `data/reinforcement/*`, `data/probabilistic/*` | runtime loop | shadow builders (read), reinforcement chain, dashboard ops | AUTHORITATIVE for belief/sensory |
| **market_context_shadow_chain** | `scripts/research/build_market_context_shadow_chain.py` via `run_live_context_refresh_once` / paper refresh | `auction_episode_*`, `cognitive_*`, `final_*`, `market_context_lifecycle_*`, visual JSON | on-demand when lifecycle tip < live tip | decision logger, paper, visual refresher | AUTHORITATIVE for context/lifecycle (de-facto production) |
| **paper_simulator_controller** | `bounded_paper_trading_controller_auto_ledger_no_real_execution.py`; pid file present, **process not alive** at snapshot | `data/research/paper_simulator/paper_*`, controller cycles | controller loop when alive; also triggers shadow+decision | visual refresher, research | AUTHORITATIVE for paper ledger |

Supporting (not a third belief plane):

| Plane | Writer | Authority |
| --- | --- | --- |
| **decision_logger** | `append_context_decision_log.py` | AUTHORITATIVE for decisions (`action_allowed=False`) |
| **visual_read_model** | `run_market_context_visual_refresher.py` (PID **37649**) + `generate_lifecycle_context_data.py` | NON_AUTHORITATIVE |

Also active sensory writers: `live_binance_feed_v2.py` (PID **97786**), `live_binance_intrabar_feed.py` (PID **93404**, non-ontology).

Inventory CSV: `data/research/write_plane_inventory.csv`.

---

## B. Canonical Paths

| Logical state | Canonical path | Duplicate / obsolete | Wrong consumers |
| --- | --- | --- | --- |
| live M15 | `data/live/live_market_feed.parquet` | intrabar = different semantics | — |
| candle / VR / MTF / reinforcement / probabilistic | pipeline paths under `data/cognition|reinforcement|probabilistic` | composite/orphan state memories | treating MTF as dense bars |
| final / lifecycle / episodes | shadow outputs under `data/cognition/` | `*.candidate_continuation` | reading candidates as prod |
| decision | `data/live/context_decision_log.parquet` | archives | — |
| paper signals/orders/trades | `data/research/paper_simulator/paper_*.parquet` | preview/policy research trades | UI using research trades as ledger |
| dashboard JSON | `apps/context_visualizer/public/data/lifecycle_latest.json` | sibling JSON files | execution consumers |
| OI / HTF / market_state | **NONE_ACTIVE** | root + diagnostics duplicates; orphan memories | dashboard DEPENDENCIES |

Full map: `data/research/canonical_path_map.csv`.  
Ownership candidate: `config/runtime_dataset_ownership.candidate.json` (**not activated**).

---

## C. Current Lag

Snapshot tips (`data/research/runtime_tip_snapshot.json`):

| Dataset | Source tip (UTC) | Notes |
| --- | --- | --- |
| live feed / candle | ~2026-07-24T10:15–10:30 | dense M15; confirms audit ~10:15+ |
| lifecycle / episode / final | 2026-07-24T09:00 | confirms shadow ~09:00 lag |
| MTF / runtime_cognition | 2026-07-23T16:00 | confirms event tip |
| decision `candle_timestamp` | 2026-07-24T08:45 | behind feed |
| paper_signals `decision_log_ts` | 2026-07-23T11:30 | controller not writing |
| controller last observation | ~2026-07-24T09:09 | STALE vs now; **paper_alive=false** |
| auction_synthesis | 2026-07-10T06:15 | frozen tip |
| OI / HTF | 2026-05-* | multi-week stale |

| Edge | Upstream tip | Downstream tip | Lag | Status |
| --- | --- | --- | ---: | --- |
| feed→candle | ~10:15–10:30 | same | ~0 | FRESH |
| candle→volume_response | candle | VR ~08:00 wall-like | ~hours | STALE (semantics caveat) |
| volume_response→auction_synthesis | VR | 2026-07-10 | days | BROKEN |
| candle→MTF | candle | 2026-07-23T16:00 | ~18h+ | EVENT_SPARSE_BY_DESIGN |
| MTF→runtime_cognition | same tip | same | 0 | EVENT_SPARSE_BY_DESIGN |
| candle→auction_episode | candle | 09:00 | ~1–1.5h | STALE |
| episode→final→lifecycle | aligned | aligned | 0 | FRESH |
| lifecycle→decision | 09:00 | 08:45 | 900s | FRESH |
| feed→lifecycle / decision | feed | 09:00 / 08:45 | ~1–1.5h | STALE |
| decision→paper_signals | 08:45 | 07-23 11:30 | ~21h+ | BROKEN |
| controller observation age | last cycle | snapshot now | >1h | STALE |

CSV: `data/research/runtime_edge_lags.csv`.

---

## D. MTF Contract

**Kind: event log (by design), not broken heartbeat alone.**

- ~165 events vs ~6.7k bars is structural, not a missing per-bar writer.  
- Downstream must use **asof inheritance with max age 86400s**.  
- Beyond max age → explicit STALE/UNSPECIFIED, not BALANCE/NEUTRAL.  
- Optional Patch 3: materialized read projection; do **not** rewrite the event log into fake dense memory without need.

Contract: `data/research/runtime_freshness_contract.json` → `mtf_contract`.

---

## E. Shadow Disposition

**`MERGE_SHARED_BUILDER`**

| Question | Answer |
| --- | --- |
| Why exists? | Restored context/lifecycle MVP outside 19-engine loop |
| Alternate production lifecycle? | **None** in pipeline |
| Builders/schemas? | Dedicated shadow builders with `builder_version`; atomic rebuild |
| Who reads? | decision logger, paper, visual |
| Why not in pipeline? | historical separation; orchestration via refresh/paper |
| Promote now? | **No** — merge ownership/orchestration later without semantic change |

Not `DEPRECATE_SHADOW` (paper depends on these paths). Not `KEEP_SHADOW_ONLY` forever (authority must be named).

---

## F. Dashboard Parity

| Metric | Value |
| --- | ---: |
| Dashboard listed engines | 24 |
| Runtime `CANONICAL_PIPELINE` | 19 |
| Phantom missing files | **6** |
| Runtime-only missing from dashboard | 1 (`auction_context_arbitration_engine_v1.py`) |

Phantoms: `volume_localization_engine_v1.py`, `market_state_engine_v1.py`, `trading_state_engine_v1.py`, `shadow_inference_engine_v1.py`, `trading_state_validation_engine_v1.py`, `economic_validation_engine_v1.py`.

CSV: `data/research/engine_registry_parity.csv`.  
**Dashboard not modified** in this task (Patch 4 later).

---

## G. OI / HTF Disposition

| Module | Fresh data? | Producer in runtime 19? | Downstream fields? | Statistical value on trade path? | Disposition |
| --- | --- | --- | --- | --- | --- |
| Open interest | No (tips May 2026) | No | No | Not proven | **FORMALLY_DEPRECATE** (cognition wire) |
| HTF structure | No (2026-05-13) | Engine file exists, not in 19 | Dashboard deps only | Not proven | **FORMALLY_DEPRECATE** |

Keep raw files as research archives; do not auto-wire.

---

## H. Belief-to-Paper Gap

```text
reinforcement / probabilistic  ──✕──►  final / lifecycle / decision / paper
cognitive / final / lifecycle   ──✓──►  decision / paper (ACTIVE_GATE)
decision confidence / edge lookup ──✓──► paper fields (CONFIDENCE_ONLY, not conviction)
```

Disconnected from paper: `alignment_score`, `persistence`, `structural_rank`, `location_bias`, `belief_strength`, `conviction_probability`, `absorption/distribution_probability`, `auction_regime`.

Active gates: `active_market_context`, `lifecycle_state`, `observe_block_reason`, `action_allowed`, freshness/`pipeline_pending`.

CSV: `data/research/belief_to_paper_lineage.csv`.  
**Probabilistic plane not wired to paper in this task.**

---

## I. Repair Patches (independent)

### Patch 1 — Ownership and metadata
Additive only: builder versions, source/evaluated timestamps, owner metadata. No semantic/tip changes.

### Patch 2 — Plane synchronization
Canonical tips; safe catch-up; no overwriting fresher state; shadow orchestration policy (`MERGE_SHARED_BUILDER`).

### Patch 3 — MTF state availability
Bounded asof inheritance / optional projection; no new trading semantics.

### Patch 4 — Dashboard/runtime parity
Show real 19 + classify phantoms; no fake ACTIVE.

### Patch 5 — Belief propagation
Only after intended-semantics proof; separate from context selection.

### Patch 1 acceptance criteria (pre-declared)

- trading states unchanged  
- historical payload unchanged  
- only additive metadata  
- no tip rollback  
- no duplicate keys  
- all datasets have owner  
- canonical consumers documented  
- flag OFF reproduces baseline  
- no runtime restart without explicit plan  

---

## J. Recommendation

**`READY_FOR_METADATA_PATCH`**

Authority is clear enough for Patch 1: owners and canonical paths are identifiable; shadow is de-facto context authority (`MERGE_SHARED_BUILDER`). Remaining BROKEN edges (`auction_synthesis` tip freeze, paper controller dead, VR timestamp semantics) are scheduled for Patch 2/forensics and **do not block additive metadata**.

Not `CANONICAL_AUTHORITY_UNCLEAR` (context owner exists). Not `DATA_PLANE_CONFLICT_BLOCKS_REPAIR` (conflicts documented; candidates already suffix-isolated).

---

## K. Safety

| Action | Done? |
| --- | --- |
| Production code changes | No |
| Production memory writes | No |
| Runtime restarts | No |
| Feature flag changes | No (`CONTINUATION=0`, `PRICE_GATE=OFF`) |
| Trading / threshold / context semantic changes | No |
| Commit / push | No |
| Research artifacts + candidate registry + tests | Yes |

### Spec / plan docs

- `docs/CANONICAL_RUNTIME_TRUTH_PIPELINE.md`
- `docs/WRITE_PLANE_CONSOLIDATION_PLAN.md`

### Research artifacts

- `config/runtime_dataset_ownership.candidate.json`
- `data/research/write_plane_inventory.csv`
- `data/research/dataset_ownership_registry.json`
- `data/research/canonical_path_map.csv`
- `data/research/write_conflicts.csv`
- `data/research/runtime_tip_snapshot.json`
- `data/research/runtime_edge_lags.csv`
- `data/research/belief_to_paper_lineage.csv`
- `data/research/engine_registry_parity.csv`
- `data/research/runtime_freshness_contract.json`
