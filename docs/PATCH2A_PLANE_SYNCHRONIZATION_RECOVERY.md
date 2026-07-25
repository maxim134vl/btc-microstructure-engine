# PATCH 2A — Plane Synchronization and Operational Recovery

**Tag:** `20260724_120015`  
**Branch:** `memory/canonical-system`  
**Basis:** Patch 1 `PATCH1_LIVE_METADATA_ACTIVATED`  
**Constraints held:** `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`, execution disabled, paper controller not started

---

## A. Result

```text
PATCH2A_SYNCHRONIZATION_RECOVERED
```

Production context/lifecycle/decision plane catch-up activated after gated candidate comparison. Feed watchdog restart contract fixed and tested. Paper remains DEAD. Dedicated recurring context refresher is prepared but **feature-flag OFF** (not activated in this patch).

---

## B. Feed Restart Contract

See [`docs/FEED_WATCHDOG_RESTART_CONTRACT.md`](FEED_WATCHDOG_RESTART_CONTRACT.md).

| Item | Detail |
| --- | --- |
| Root cause | Zombie treated as alive; bare Cellar lacked `websocket` |
| Interpreter | `<repo>/venv/bin/python` only (path string under venv) |
| Zombie | Classified dead; reap; single restart; dual-writer prevention |
| Backoff | Windowed attempts → `RESTART_STORM_BLOCKED` |
| Tests | `tests/test_collector_watchdog_restart_contract.py` — 13 cases |

Live topology at close (PIDs may drift):

- watchdog → feed child (parent relationship intact)
- `run.py` alive
- visual refresher alive (read-model only)
- paper controller DEAD (`pidfile` stale, process absent)

---

## C. Auction Synthesis Disposition

Artifact: `data/research/patch2a_auction_synthesis_disposition.json`

```text
ACTIVE_BROKEN
+ WRITER_DISCONNECTED
+ ACTIVE_CONSUMER_READING_STALE_FILE
```

- Path: `data/reinforcement/auction_synthesis_memory.parquet`
- Tip ~ `2026-07-10` (stale)
- Canonical writer disconnected / dependency-guard skip path
- **Not** on context-truth dependency chain
- Patch 2A action: **no rebuild, no delete**; keep `force_health=BROKEN`; context recovery proceeded independently
- Not classified as legacy orphan / replacement dataset

---

## D. Context Lag Root Cause

Artifact: `data/research/patch2a_context_lag_root_cause.json`

Pre-recovery tips:

| Plane | Tip |
| --- | --- |
| feed | ~11:45Z |
| final / lifecycle | ~09:00Z |
| decision | ~08:45Z |

Root cause chain:

1. Context truth writers are shadow chain + decision logger (`MERGE_SHARED_BUILDER` / CONTEXT_TRUTH).
2. Live visual refresher is read-model only and forbids shadow rebuild.
3. Historical continuous trigger was the bounded paper controller; paper is DEAD → no automatic catch-up.
4. `run_live_context_refresh_once` existed but was on-demand only.
5. Sensory/belief (`feed` + `run.py`) advanced while context plane froze.

Not causes: feed failure after Patch 1; metadata sidecars blocking writes; auction_synthesis freeze (belief-only).

---

## E. Shared Builder

```text
MERGE_SHARED_BUILDER
```

Canonical implementation remains the existing shared builders invoked by:

- historical/backfill paths
- `run_live_context_refresh_once` / shadow chain
- candidate catch-up (`scripts/ops/patch2a_candidate_context_catchup.py`)

No second diverging classifier introduced. Lifecycle activation used **tail-merge** (not full replace) because replay can diverge on `lifecycle_state` while preserving `active_market_context` / invalidation / `action_allowed` identity on the historical prefix.

---

## F. Candidate Comparison

Artifacts:

- `data/research/patch2a_candidate_20260724_120015/`
- `data/research/patch2a_candidate_comparison.json`

| Gate | Result |
| --- | --- |
| `gates_pass` | **true** |
| Historical prefix identical | yes (final / lifecycle fields checked / decision existing rows) |
| New tail only | +11 context rows to 11:45Z; +12 decision rows after 08:45Z |
| Duplicate keys | 0 |
| Tip rollback | false |
| Candidate ≤ feed tip | true |

Statuses at candidate tip proof: feed / final / lifecycle / decision all `FRESH` relative to safe upstream M15 tip (then 11:45Z).

---

## G. Production Activation

Artifact: `data/research/patch2a_production_preservation.json`  
Backups: `data/research/patch2a_production_backups_20260724_120015/`

Mode: atomic **tail_merge** (existing rows win; append missing timestamps only).

| Dataset | Tip before | Tip after activation | Mode |
| --- | --- | --- | --- |
| final_market_context_memory | 09:00Z | 11:45Z | tail_merge |
| market_context_lifecycle_memory | 09:00Z | 11:45Z | tail_merge |
| context_decision_log | 08:45Z | 11:45Z | tail_merge |
| auction_episode / cognitive | 09:00Z | 11:45Z | tail_merge |

Post-activation on-demand refresh advanced tips to **12:00Z** (aligned with feed). Sidecars: `metadata_origin=LIVE_WRITER` via writer path. Runtime status rebuilt.

Paper SHA before/after activation: **identical**.

---

## H. Recurring Refresh Ownership

```text
DEDICATED_CONTEXT_REFRESHER
```

Rationale: exactly one authoritative trigger independent of paper and visual UI; reuse once-refresh semantics; do not make visual refresher own context truth.

Prepared control (default disabled):

```text
scripts/ops/context_refresh_daemon_ctl.sh
BTC_ML_CONTEXT_REFRESH_DAEMON=1   # required to start
```

**Not activated in Patch 2A.** Until flag enablement, catch-up remains on-demand (`run_live_context_refresh_once`) / ops-driven. Activation plan: enable only after lock/idempotency/single-writer checks under live load.

---

## I. Live Cycles

Artifact: `data/research/patch2a_live_cycles.json`

| Cycle | Status |
| --- | --- |
| activation_sync → 11:45Z | ALIGNED_AT_FEED_TIP |
| post_activation_once_refresh → 12:00Z | ALIGNED |

Natural multi-hour M15 soak not awaited in this patch window; two consecutive completed bars proved feed → context → lifecycle → decision with `LIVE_WRITER` sidecars and no paper dependency.

---

## J. Current Health

From `data/runtime/runtime_dataset_status.json` after recovery (representative):

| Health | Datasets |
| --- | --- |
| FRESH | live_market_feed, candle_structure, auction_episode, cognitive, final_market_context, lifecycle (+ latest json), context_decision_log, reinforcement/probabilistic (as registered) |
| BROKEN | auction_synthesis_memory, paper_signals, paper_orders, paper_trades |
| EVENT_SPARSE_BY_DESIGN | multi_timeframe_synthesis, runtime_cognition_memory, volume_response_state |
| INACTIVE_DEPRECATED / PHANTOM / UNKNOWN | unchanged Patch 1 classifications (htf/oi orphans, etc.) |

---

## K. Tests

Commands:

```bash
export BTC_ML_CONTINUATION_PROGRESSION=0 PRICE_GATE=OFF
venv/bin/python -m pytest \
  tests/test_collector_watchdog_restart_contract.py \
  tests/test_runtime_dataset_metadata_patch1.py \
  tests/test_write_plane_consolidation_candidate.py \
  tests/test_context_decision_logger.py \
  tests/test_live_context_refresh_once.py \
  tests/test_market_context_lifecycle_memory.py \
  tests/test_auction_episode_memory.py \
  tests/test_runtime_dependency_guard.py \
  -q
```

Result: **167 passed**, 3 warnings (known non-fatal).

Paper controller preview failures remain **Patch 2B debt** (not run as blockers here).

---

## L. Safety

| Check | Status |
| --- | --- |
| Paper controller | DEAD (no process; pidfile stale) |
| Paper signals/orders/trades SHA | unchanged vs pre-activation |
| MTF Patch 3 | not started; event-sparse unchanged |
| Dashboard Patch 4 | not started |
| Belief→paper Patch 5 | not started |
| Execution / exchange | disabled / no calls |
| CONTINUATION | OFF (`0`) |
| PRICE_GATE | OFF |
| Commit / push | not performed |

---

## M. Next Step

```text
PATCH 2B — PAPER CONTROLLER FORENSICS AND RECOVERY
```

Do **not** start Patch 2B from this document. Optional ops follow-up before 2B: enable `BTC_ML_CONTEXT_REFRESH_DAEMON=1` only after an explicit activation checklist, or continue on-demand refresh until then.

---

## Artifacts index

| Path | Role |
| --- | --- |
| `data/research/patch2a_preflight_20260724_120015.json` | Preflight snapshot |
| `data/research/patch2a_dependency_recovery_graph.json` | Recovery DAG |
| `data/research/patch2a_auction_synthesis_disposition.json` | Auction disposition |
| `data/research/patch2a_context_lag_root_cause.json` | Lag RCA + ownership |
| `data/research/patch2a_candidate_comparison.json` | OLD vs candidate gates |
| `data/research/patch2a_production_preservation.json` | Backups / activation |
| `data/research/patch2a_live_cycles.json` | Live tip proofs |
| `docs/FEED_WATCHDOG_RESTART_CONTRACT.md` | Restart contract |
| `scripts/ops/patch2a_candidate_context_catchup.py` | Candidate builder |
| `scripts/ops/context_refresh_daemon_ctl.sh` | Disabled dedicated refresher |
| `collector_watchdog.py` | Restart contract implementation |
