# PATCH 1 — Runtime Ownership and Metadata

**Result:** `METADATA_PATCH_READY_FOR_LIVE_ACTIVATION`  
**Branch:** `memory/canonical-system`  
**Flags frozen:** `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`, execution disabled  
**Patch 2:** not started

---

## A. Patch Result

```text
METADATA_PATCH_READY_FOR_LIVE_ACTIVATION
```

Code + active registry + bootstrap sidecars + status snapshot are in place. Live writer instrumentation is compiled into writers but **not activated** until listed processes are restarted under a separate activation step.

---

## B. Files Changed

### Production / shared code
- `runtime_dataset_metadata.py` (**new** shared library)
- `src/btc_ml/runtime/pipeline.py` — best-effort sidecar emit after cycle
- `scripts/research/build_market_context_shadow_chain.py` — emit after PASS
- `scripts/live/append_context_decision_log.py` — emit after decision write
- `scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py` — emit after ledger append
- `apps/context_visualizer/generate_lifecycle_context_data.py` — emit after `lifecycle_latest.json`
- `live_binance_feed_v2.py` — emit after feed save

### Config
- `config/runtime_dataset_ownership.json` (**new** active registry)
- `config/runtime_dataset_ownership.candidate.json` (prior candidate; retained)

### Ops
- `scripts/ops/bootstrap_runtime_dataset_metadata.py` (**new**)

### Tests / docs / research
- `tests/test_runtime_dataset_metadata_patch1.py`
- `docs/PATCH1_RUNTIME_OWNERSHIP_METADATA.md`
- `data/research/patch1_pre_sha256.json`
- `data/research/patch1_bootstrap_preservation.json`

### Derived (non-parquet) artifacts written by bootstrap
- `data/runtime/runtime_dataset_status.json`
- `*.meta.json` sidecars next to registered datasets

---

## C. Registry

| Metric | Count |
| --- | ---: |
| Datasets | 24 |
| Planes | 5 (`canonical_pipeline_loop`, `market_context_shadow_chain`, `paper_simulator_controller`, `decision_logger`, `visual_read_model`) |
| Authority roles | `SENSORY_BELIEF`, `CONTEXT_TRUTH`, `PAPER_LEDGER`, `DERIVED_DECISION_LOG`, `NON_AUTHORITATIVE_READ_MODEL`, `NONE` (deprecated/phantom) |

Context/lifecycle plane:

```text
legacy_name = market_context_shadow_chain
authority_role = CONTEXT_TRUTH
```

Warning retained:

```text
maximum_inheritance_age_seconds=86400 is inherited current policy,
not yet scientifically or operationally validated for downstream trading.
```

---

## D. Bootstrap

- 24 sidecars written with `metadata_origin=BOOTSTRAP_READ_ONLY`
- Status snapshot: `data/runtime/runtime_dataset_status.json`
- Per-file sha256 before/after each sidecar write: **unchanged**
- Proof: `data/research/patch1_bootstrap_preservation.json`

---

## E. Production Preservation

Patch 1 does **not** rewrite parquet schemas or payloads. Bootstrap proof confirms sha256 identity around sidecar writes.

Concurrent live processes (`run.py`, live feed) may update their own parquet independently of Patch 1; that is outside Patch 1 mutation scope.

---

## F. Current Health (snapshot)

From `data/runtime/runtime_dataset_status.json` at bootstrap time (counts approximate):

| Health | Count | Examples |
| --- | ---: | --- |
| FRESH | 4 | feed/candle/reinforcement/probabilistic (as classified) |
| STALE | 6 | lifecycle/final/episode/decision vs feed lag |
| BROKEN | 2 | `auction_synthesis_memory`, `paper_signals` |
| DEAD_WRITER | 2 | `paper_orders`, `paper_trades` (controller DEAD) |
| EVENT_SPARSE_BY_DESIGN | 3 | MTF, runtime_cognition, volume_response |
| INACTIVE_DEPRECATED | 4 | OI + disconnected HTF paths |
| PHANTOM | 2 | market_state / trading_state orphans |
| UNKNOWN | 1 | — |

Not fixed in Patch 1 (only classified): lifecycle ~09:00 lag, decision lag, paper tip, MTF event tip, auction_synthesis ~2026-07-10, dead paper PID, dashboard 24 vs 19, CONTINUATION OFF, BALANCE semantics.

---

## G. Restart Requirements (do **not** execute here)

| Process | Observed | Why restart needed for LIVE_WRITER metadata |
| --- | --- | --- |
| `run.py` canonical pipeline | PID 20908 (was active) | load pipeline metadata emit hook |
| `live_binance_feed_v2.py` | active | load feed metadata emit hook |
| `run_market_context_visual_refresher.py` | active | pick up generate_lifecycle sidecar emit |
| paper controller | **DEAD** — do not start in Patch 1 | instrumentation present; start only under later activation |
| shadow chain | on-demand via refresh/paper | next successful chain run emits CONTEXT_TRUTH sidecars |
| decision logger | on-demand | next append emits decision sidecar |

Activation Step C requires explicit approval before any restart.

---

## H. Tests

```bash
venv/bin/python scripts/ops/bootstrap_runtime_dataset_metadata.py
venv/bin/python -m pytest tests/test_runtime_dataset_metadata_patch1.py tests/test_write_plane_consolidation_candidate.py -q
venv/bin/python -m pytest tests/test_auction_episode_memory.py tests/test_market_context_lifecycle_memory.py tests/test_observe_directional_context_audit.py -q
venv/bin/python -m pytest tests/test_context_decision_logger.py tests/test_live_decision_log_freshness_cadence_readiness.py tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py tests/test_dashboard_decision_source_freshness.py -q
```

Observed: metadata + consolidation **41 passed**; auction/lifecycle/observe **75 passed**; decision/freshness/paper suite run separately (see command output in session).

---

## I. Safety

| Check | Status |
| --- | --- |
| No parquet schema/payload mutation by Patch1 | Yes |
| No auction/context/decision/paper semantic changes | Yes |
| No exchange / execution | Yes |
| CONTINUATION=0 / PRICE_GATE=OFF | Yes |
| No automatic restart | Yes |
| No commit/push | Yes |
| Metadata not used for LONG/SHORT/OBSERVE/action_allowed | Yes |

---

## J. Next Patch

Only after live metadata activation (Step C):

```text
PATCH 2 — plane synchronization and operational recovery
```

Do not start Patch 2 inside this task.
