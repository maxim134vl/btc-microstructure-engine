# Canonical Runtime Truth Pipeline (Candidate Spec)

**Status:** candidate specification — **not activated in production**
**Frozen flags:** `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`, execution disabled
**Source audit:** `docs/FULL_MODEL_ARCHITECTURE_AUDIT.md` + `scripts/research/run_write_plane_consolidation_audit.py`

Goal: every production state has one owner, one canonical active path, an explicit freshness contract, and a single downstream consumer chain. **No auction/trading semantic changes in this spec.**

---

## 1. One writer per dataset

Authoritative candidate registry:

- `config/runtime_dataset_ownership.candidate.json`
- mirror: `data/research/dataset_ownership_registry.json`

| Dataset | Canonical writer | Entrypoint |
| --- | --- | --- |
| `data/live/live_market_feed.parquet` | live market feed writer | `live_binance_feed_v2.py` |
| `data/cognition/candle_structure_memory.parquet` | canonical pipeline loop | `candle_structure_engine_v1.py` |
| `data/cognition/volume_response_state.parquet` | canonical pipeline loop | `volume_response_engine_v1.py` |
| `data/reinforcement/auction_synthesis_memory.parquet` | canonical pipeline loop | `auction_synthesis_engine_v1.py` |
| `data/cognition/multi_timeframe_synthesis.parquet` | canonical pipeline loop | `stage2_cognition_runtime_v1.py` |
| `data/cognition/runtime_cognition_memory.parquet` | canonical pipeline loop | `runtime_cognition_engine_v1.py` |
| `data/reinforcement/auction_reinforcement_memory.parquet` | canonical pipeline loop | `auction_reinforcement_engine_v1.py` |
| `data/probabilistic/probabilistic_auction_memory.parquet` | canonical pipeline loop | `probabilistic_auction_engine_v1.py` |
| `data/cognition/auction_episode_memory.parquet` | market context shadow chain | `scripts/research/build_auction_episode_memory.py` |
| `data/cognition/cognitive_market_state_memory.parquet` | market context shadow chain | `scripts/research/build_cognitive_market_state_memory.py` |
| `data/cognition/final_market_context_memory.parquet` | market context shadow chain | `scripts/research/build_final_market_context_memory.py` |
| `data/cognition/market_context_lifecycle_memory.parquet` | market context shadow chain | `scripts/research/build_market_context_lifecycle_memory.py` |
| `data/cognition/market_context_lifecycle_episodes.parquet` | market context shadow chain | same lifecycle builder |
| `data/live/context_decision_log.parquet` | decision logger | `scripts/live/append_context_decision_log.py` |
| `data/research/paper_simulator/paper_{signals,orders,trades}.parquet` | paper controller | `scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py` |
| `apps/context_visualizer/public/data/lifecycle_latest.json` | visual JSON builder | `generate_lifecycle_context_data.py` |

Research/candidate outputs must use distinct suffixes (e.g. `.candidate_*`) and never share production paths.

---

## 2. Canonical paths

See `data/research/canonical_path_map.csv`.

Rules:

- Context/lifecycle truth = shadow-chain outputs under `data/cognition/*` (de-facto production today).
- Belief truth = canonical 19-engine pipeline memories.
- Paper ledger truth = `data/research/paper_simulator/paper_*.parquet`.
- Dashboard JSON = **non-authoritative read model**.
- `NONE_ACTIVE` for OI, HTF structure, market/trading_state phantoms until explicitly re-owned.

---

## 3. Source / evaluated timestamps

Every write must eventually carry:

| Field | Meaning |
| --- | --- |
| `source_timestamp` | market bar / event time used for asof joins |
| `evaluated_timestamp` | when the engine/builder computed the row |
| `builder_version` | immutable string per builder |

**File mtime is ops-only and never a substitute for `source_timestamp`.**

Known defect to fix only in Patch 1 metadata (no semantics): several pipeline memories currently store wall-clock-like values in `timestamp` (e.g. volume_response, reinforcement).

---

## 4. Freshness budgets

Candidate contract: `data/research/runtime_freshness_contract.json`.

| Edge | Budget |
| --- | ---: |
| feed → candle | 1200s |
| candle → volume_response | 1800s |
| candle → auction_episode | 1800s |
| episode → final → lifecycle | 900s each |
| lifecycle → decision | 1800s |
| decision → paper_signals | 3600s |
| MTF event inheritance max age | 86400s |

Statuses: `FRESH` | `PIPELINE_PENDING` | `STALE` | `EVENT_SPARSE_BY_DESIGN` | `BROKEN`.

---

## 5. Event-sparse inheritance (MTF)

`multi_timeframe_synthesis` is an **event log**, not per-bar memory.

Downstream availability:

1. Prefer last event with `event_ts <= bar_ts` (asof).
2. If `bar_ts - event_ts > max_inherited_age_seconds` (86400): mark `MTF_STATE_STALE` / unspecified — **do not** coerce to BALANCE/NEUTRAL/OBSERVE.
3. Optional Patch 3: materialized per-bar **read projection** that does not replace the event log.

`runtime_cognition` follows the same event-sparse contract.

---

## 6. Shadow promotion rules

**Disposition: `MERGE_SHARED_BUILDER`**

- There is no separate “production lifecycle” inside the 19-engine pipeline.
- Shadow builders already write the only active context/lifecycle paths.
- Future consolidation merges **orchestration** (freshness-gated catch-up) into the truth chain schedule.
- Semantics of classify/build functions stay frozen.
- Candidates remain suffix-isolated.
- **No promotion in this task.**

---

## 7. Consumer map

```text
live_binance_feed_v2
  → candle_structure_engine_v1 → … → stage2/MTF → reinforcement → probabilistic
                                      ↘ (read-only inputs)
build_market_context_shadow_chain
  → auction_episode → cognitive → final → lifecycle
      → append_context_decision_log
          → bounded_paper_trading_controller (paper_* only)
      → generate_lifecycle_context_data / visual refresher (read model)
```

Belief plane does **not** currently gate paper (by observed lineage). Patch 5 may connect it only after intended-semantics proof; out of scope here.

---

## 8. Error / fallback behavior

| Condition | Required behavior |
| --- | --- |
| Missing upstream | skip or fail-closed with explicit code; never silent BALANCE/NEUTRAL |
| Engine skipped | tip freeze must surface as STALE/BROKEN in ops |
| Shadow lag | `PIPELINE_PENDING` / refresh catch-up; decision may append only for available bars |
| Corrupt parquet | refuse overwrite; alert; no tip rollback from older candidate |
| Dashboard phantom engine | display DISABLED/MISSING; never imply ACTIVE |

---

## 9. Rollback rules

1. Feature flags OFF reproduce baseline.
2. Metadata-only patches must be additive and reversible by ignoring new columns.
3. Older candidate artifact must never replace a newer production tip.
4. Shadow rebuild that would shorten tip vs prior tip requires explicit human approval (Patch 2).
5. No runtime restart without an explicit plan naming PIDs and expected tip continuity.

---

## 10. Invariants

Align with `docs/CANONICAL_MODEL_INVARIANTS.md`, especially:

- one owner / one active path;
- missing ≠ NEUTRAL;
- research does not write production;
- mtime ≠ source timestamp;
- CONTINUATION progression remains OFF;
- action_allowed remains fail-closed;
- no exchange execution from paper path.
