# PATCH 1 — Live Metadata Activation

Timestamp tag: `20260724_111507`

## A. Result

```text
PATCH1_LIVE_METADATA_ACTIVATED
```

Required live writers restarted safely, metadata hooks loaded, natural `LIVE_WRITER` sidecars confirmed for feed / pipeline / visual, historical trading payload unchanged, paper controller remained dead.

## B. Preflight

| Item | Value |
| --- | --- |
| Branch | `memory/canonical-system` |
| Worktree | left untouched (no cleanup of unrelated dirty files) |
| Flags | `BTC_ML_CONTINUATION_PROGRESSION=0`, `PRICE_GATE=OFF`, execution disabled |
| Paper | PID file `25953`, process dead |
| Backup dir | `data/research/patch1_live_activation_backups_20260724_111507/` |
| Code SHAs | `data/research/patch1_live_activation_code_sha_20260724_111507.txt` |
| Preflight JSON | `data/research/patch1_live_activation_preflight_20260724_111507.json` |

### Pre-activation inventory (authoritative PIDs)

| Process | Old PID | PPID / supervisor | Interpreter (ps) | cwd |
| --- | ---: | --- | --- | --- |
| `collector_watchdog.py --required-only` | 20895 | 1 | Cellar Python.app path | repo |
| `live_binance_feed_v2.py` | 97786 | 20895 (watchdog) | Cellar Python.app path | repo |
| `run.py` | 20908 | 1 | Cellar Python.app path | repo |
| visual refresher | 37649 | 1 | Cellar Python.app path | repo |
| paper controller | — | — | — | DEAD |

Note: on macOS, `venv/bin/python` resolves in `ps` to the Cellar Frameworks binary. Canonical stack launcher (`scripts/runtime_stack.sh`) uses `venv/bin/python3`.

## C. Restarted Processes

Process journal: `data/research/patch1_live_activation_processes_20260724_111507.json`

| Process | Old PID → New PID | Interpreter used | cwd | Supervisor / control path |
| --- | --- | --- | --- | --- |
| collector watchdog | 20895 → **96675** | `venv/bin/python` | repo | watchdog-only bounce (runtime_stack stop/start semantics) after zombie feed blocked auto-restart |
| live feed | 97786 → **96678** | via watchdog `sys.executable` | repo | child of watchdog 96675 |
| `run.py` | 20908 → **96691** | `venv/bin/python` | repo | SIGTERM + detach-start `BTC_ML_ENGINE_EXECUTION_MODE=persistent_worker` |
| visual refresher | 37649 → **96805** | `venv/bin/python` via `PYTHON=` | repo | `scripts/context_visual_stack_ctl.sh` stop/start, interval 20s |

### Feed recovery detail (required for integrity)

1. First SIGTERM left feed as zombie (`STAT=Z`, argv `<defunct>`).
2. Watchdog `os.kill(pid, 0)` treats zombies as alive → no auto-restart (restart storm avoided, but feed stayed down).
3. Canonical recovery: bounce **watchdog only** (not full `runtime-stack restart`).
4. Bare Cellar executable without venv site-packages failed once (`ModuleNotFoundError: websocket`).
5. Restart with canonical `venv/bin/python` succeeded; websocket connected; natural candle append resumed.

Post-activation uniqueness: one watchdog, one feed child, one `run.py`, one visual refresher. Paper still absent.

## D. Sidecar Activation

Sidecar table: `data/research/patch1_live_activation_sidecars_20260724_111507.json`

| Dataset | Before origin | After origin | Writer PID | Live write confirmed |
| --- | --- | --- | ---: | --- |
| `live_market_feed` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96678 | yes |
| `candle_structure_memory` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `volume_response_state` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `auction_synthesis_memory` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `multi_timeframe_synthesis` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `runtime_cognition_memory` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `auction_reinforcement_memory` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `probabilistic_auction_memory` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96691 | yes |
| `lifecycle_latest_json` | `BOOTSTRAP_READ_ONLY` | `LIVE_WRITER` | 96805 | yes |
| `context_decision_log` | `LIVE_WRITER` (pre-existing pid 87915) | unchanged payload | 87915 | pre-existing sidecar; no activation write |
| lifecycle / final context / paper / OI / HTF / phantoms | `BOOTSTRAP_READ_ONLY` | still bootstrap or honest non-live | — | `HOOK_LOADED_NOT_YET_LIVE_CONFIRMED` (no forced Patch 2 writes) |

Feed sidecar fields after natural append:

- `metadata_origin = LIVE_WRITER`
- `writer_entrypoint = live_binance_feed_v2.py`
- `canonical_writer = live_market_feed_writer` (registry name)
- `writer_pid = 96678`

## E. Production Preservation

Artifact: `data/research/patch1_live_activation_preservation_20260724_111507.json`

| Dataset | Mode | Historical prefix OK |
| --- | --- | --- |
| `live_market_feed` | natural append `3506 → 3508`, tip `11:00Z → 11:30Z`, schema unchanged | true |
| lifecycle / final context / decision | unchanged sha256 + rows + tip | true |
| paper signals/orders/trades | unchanged sha256 + rows | true |
| pipeline cognition outputs that wrote | natural append / same-schema live update | no tip rollback / no row decrease |

No historical rebuild. No schema change on production market feed.

## F. Current Runtime Health

Rebuilt: `data/runtime/runtime_dataset_status.json`

Honest classifications after activation:

| Health | Datasets |
| --- | --- |
| FRESH | `live_market_feed`, `candle_structure_memory`, `auction_reinforcement_memory`, `probabilistic_auction_memory` |
| STALE | lifecycle, final context, decision, auction_episode, cognitive_market_state, lifecycle_latest_json |
| BROKEN | `auction_synthesis_memory`, `paper_signals` |
| DEAD_WRITER | `paper_orders`, `paper_trades` |
| EVENT_SPARSE_BY_DESIGN | MTF, runtime_cognition, volume_response |
| INACTIVE_DEPRECATED | OI / HTF paths |
| PHANTOM | orphan market/trading_state |
| UNKNOWN | lifecycle episodes |

Broken/stale/dead were **not** artificially flipped to FRESH.

Pipeline: `CANONICAL_PIPELINE` length **19**; cycle counter continued (`20 → 23` during observation); no metadata-driven fail storm. `auction_synthesis_engine_v1.py` remains dependency-skipped as before.

## G. Trading Invariants

Artifact: `data/research/patch1_live_activation_trading_20260724_111507.json`

```text
historical_trading_payload_changed = false
```

On pre-activation tip timestamps:

- final `market_context` = `SHORT_CONTEXT` (unchanged)
- lifecycle `active_market_context` = `SHORT_CONTEXT` (unchanged)
- auction episode = `ACCEPTANCE_LOWER` (unchanged)
- decision tip/rows/hash unchanged
- paper signal/order/trade hashes unchanged

Metadata is not consulted by trading classifiers/gates.

## H. Paper Test Debt

Classification:

```text
KNOWN_NONBLOCKING_PAPER_PREVIEW_DEBT
```

Exact failing tests (captured in `data/research/patch1_live_activation_paper_failures_20260724_111507.txt`):

1. `tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py::test_04_long_short_stop_take_context_and_stop_first`
2. `tests/test_bounded_paper_trading_controller_auto_ledger_no_real_execution.py::test_08_flat_entry_gate_and_synthetic_price_forbidden`

Failures are preview/`allowed` assertions. They do not pass through `runtime_dataset_metadata.py`, ownership registry, sidecar emission, or health classification. Paper controller was **not** started.

## I. Rollback Readiness

Exact instrumented code/config backups:

```text
data/research/patch1_live_activation_backups_20260724_111507/
```

Restore only those files (no `git reset` / worktree wipe). Then restart only the affected process via:

- feed: bounce watchdog / let watchdog restart child (`venv/bin/python collector_watchdog.py --required-only`)
- runtime: SIGTERM `run.py` + detach-start with `venv/bin/python` + `persistent_worker`
- visual: `PYTHON=venv/bin/python CONTEXT_VISUAL_INTERVAL_SECONDS=20 bash scripts/context_visual_stack_ctl.sh restart`

## J. Safety

- no Patch 2
- no lifecycle catch-up / context rebuild / decision backfill / shadow refresh
- no `auction_synthesis` rebuild
- no paper controller start
- no trades / orders / ledger mutation
- no exchange/API trading calls beyond existing market websocket feed
- no feature-flag changes
- no commit / push

## K. Next Step

Only after this successful activation:

```text
PATCH 2 — PLANE SYNCHRONIZATION AND OPERATIONAL RECOVERY
```

Patch 2 was **not** started in this task.
