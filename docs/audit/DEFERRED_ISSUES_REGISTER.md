# Deferred Issues Register

Created for Stage 1A. Issues here are observed but **not** fixed in Stage 1A unless they block the volume chain candidate.

| ID | Timestamp (UTC) | Component | Symptom | Evidence | Potential impact | Blocks Stage 1A | Recommended stage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEFERRED-DUAL-FEED | 2026-07-26T13:38Z | live_feed_v2 + intrabar | Two feed processes concurrent | baseline_manifest processes PIDs 93106 + 93404 | Ambiguous market data authority | no | Data-plane cleanup after Stage 1 |
| DEFERRED-OI-ABSENT | 2026-07-26T13:38Z | oi_collector | Process absent; OI tip May 2026 | baseline `btc_oi` HISTORICAL_ONLY | Incomplete inventory/participation model | no | Later data-layer stage |
| DEFERRED-SYNTHESIS-STALE | 2026-07-26T13:38Z | auction_synthesis | Artifact tip ~2026-07-10; HTF deps frozen | baseline / audit | No live synthesis into cognition | no | Post Stage 1 synthesis restoration |
| DEFERRED-H4-BOOKS-MISSING | 2026-07-26T13:38Z | trader_H4 | orders/fills/positions/trades absent | baseline trading_books | H4 paper book gap | no | Trader book integrity |
| DEFERRED-UI-AST-CALL | 2026-07-26T12:31Z | OPS UI | UI may show ast.Call / runtime_truth_unavailable | audit: API OK, UI symptom | Misleading ops view | no | OPS/UI stage |
| DEFERRED-LAUNCHER-LIFECYCLE | 2026-07-26 | runtime_stack | Agent-shell vs detached lifecycle deaths during prior activation | stability gate | Pipeline SIGTERM risk | no | Runtime ops hardening (not Stage 1A) |
| DEFERRED-LOG-ROTATION | 2026-07-26 | runtime.log | ~1GB log; no rotation | baseline / prior gate | Ops pain; not proven sole death cause | no | Logging ops |
| STAGE1B-HARDENING-INDEX | 2026-07-26T14:25Z | `runtime_hardening.py` | Absolute `[12]` index blocked 21-step activation | Resolved by relative-order validator in `6972e30` | was yes for Stage 1B | **resolved** | Stage 1B amendment complete |
| DEFERRED-PATCH-EXPECTED-20 | 2026-07-26T14:40Z | patch3.2 / patch4.2 / write_plane tests | Still assert expected step count 20 in source text | Outside Stage 1 relevant suite | no | Later dashboard/ops test alignment |
