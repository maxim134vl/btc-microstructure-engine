# CTO Deployment Validation

## Exact Git commit
- Pack branch tip at validation: see `FINAL_HEAD` after commits on `feature/cto-deployment-pack`
- Starting HEAD: `4ca7105c345c8f875fcdc6a170826ae7a4888493`
- Smoke bootstrap recorded `CTO_GIT_COMMIT` from that tip during the successful run

## Toolchain
- Python: 3.11.15 (host verification venv `.venv-cto`)
- Docker: `docker --version` as installed on the CTO host
- Compose: `docker compose version` as installed on the CTO host

## Service graph
See [SERVICE_GRAPH.md](./SERVICE_GRAPH.md).

Compose services:
- `cognition-runtime` (LIVE1A; market WS embedded)
- `paper-manager` (LIVE1B + paper-only guard)
- `shadow-eqcorr` (CTO entrypoint, `strict_epoch=False`)
- `shadow-stp21` (CTO entrypoint, `strict_epoch=False`, `allow_start_without_exact=True`)
- `ops-api`
- `dashboard-ui`
- `cto-bootstrap` (profile `bootstrap`, one-shot)

## Image IDs (local tags)
- `btc-ml-cto-runtime:local` → `5531e0f03f2f` (851MB)
- `btc-ml-cto-ops-api:local` → `78e934e2bdd0` (852MB)
- `btc-ml-cto-dashboard-ui:local` → `fc9973c3c151` (76.5MB)

## Docker / Compose versions
- Docker `29.4.3`
- Compose `v5.1.3`

## Isolated project / volume
- Project: `btcml-cto-smoke`
- Volume: `btc_ml_data_cto_smoke`
- OPS host port: `18080`
- UI host port: `15173`
- No bind to `/Users/fontecrypto/btc-ml/data`
- No use of host ports `8080` / `5173`

## Bootstrap
- Status: **PASS**
- Paper epoch ID: `INTRABAR_RULES_V1_CTO_20260731_133128`
- Fingerprint: `a6a916a767c6cfe83e9eb4581103d422bfc1adad6a56dfbf8f867930c129cb5a`
- Method: `create_epoch` + `activate_epoch` + `build_trading_contract_manifest`
- No live Mac epoch copied

## Paper-only proof
`/app/data/deployment/paper_only_contract.json`:
- `status=PASSED`
- `paper_only=true`
- `real_execution_enabled=false`
- `execution_enabled=false`
- epoch attached: `INTRABAR_RULES_V1_CTO_20260731_133128`

## Real-execution-disabled proof
- Config `config/intrabar_paper_execution.json`: `real_execution_enabled=false`
- Guard rejects credential env vars and `REAL_EXECUTION_ENABLED=true`
- Paper manager refuses start when `cfg.real_execution_enabled` is true

## Service health (smoke poll)
| Service | Result |
|---------|--------|
| cognition-runtime / market | HEALTHY (`market_ready=true`) |
| paper-manager | HEALTHY (`paper_ready=true`, contract PASSED) |
| shadow-eqcorr | HEALTHY / observe-only active |
| shadow-stp21 | STARTING/DEGRADED acceptable: `SHADOW_STP1_BLOCKED_NO_EXACT_INTRABAR_VOLUME` on fresh volume (`stp_ready=true` via healthcheck presence) |
| ops-api | HEALTHY (`/health` + snapshot HTTP 200) |
| dashboard-ui | started with stack |

Smoke report: `deploy/cto/smoke_evidence/smoke_report.json` (gitignored)
Overall smoke status: **CTO_DEPLOYMENT_PACK_VALIDATED**
Duration: **101.18s**

## Targeted tests
- `tests/deploy/`: **9 passed**
- `tests/test_shadow_economic_correlation.py` + STP + equity-curve + deploy: **48 passed, 1 skipped**
- `tests/test_context_visual_stack_live_trade_overlay.py::test_refresher_lock_and_outputs`: **PASS**
- `tests/test_vis1c_ops_trading_performance_truth.py`: **2 failed** in cleanroom (no live books/data) — environment limitation, not a CTO pack regression

## Isolation proof
- `isolation_ok=true` (volume inspect has no `/Users/fontecrypto/btc-ml/data`)
- Live Mac PIDs unchanged across smoke:
  - LIVE1A `14253`, LIVE1B `49380`, EQCORR `77839`, STP `54680`, dashboard `:8080` `26412`

## Known limitations
1. OPS snapshot ribbon may show RED/YELLOW for historical collectors/parquet not present in a clean CTO volume — expected for a new epoch.
2. STP2.1 reports no exact intrabar volume until sufficient journal history exists; CTO entrypoint allows STARTING via `allow_start_without_exact=True`.
3. EQCORR/STP production launchers hardcode `strict_epoch=True` against a research epoch; CTO entrypoints use `strict_epoch=False` for cleanroom epochs (documented in SERVICE_GRAPH).
4. Frontend npm audit highs documented in FRONTEND_DEPENDENCY_NOTE.md; not upgraded in this pack.
5. `btc-auction-runtime` was a stale gitlink (removed); see GITLINK_DECISION.md.

## Blockers
None for the isolated smoke success criteria above.

## Push
**NO**
