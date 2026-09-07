# VPS Full-Model Service Graph

Derived from host hybrid launchers in `scripts/btc_ml_host.py`
(`model_start()` + `MODEL_CTLS` + dashboard profile).
**No compose profiles exclude EQCORR or any other required unit.**

Paths are relative to the container repo root `/app`.

## Graph overview

```
Binance public WS
       │
       ▼
┌──────────────────────┐     ┌─────────────────────────┐
│  collector-watchdog  │     │   canonical-runtime     │
│  (required collectors)│     │        (run.py)         │
└──────────────────────┘     └─────────────────────────┘
       │
       ▼
┌──────────────────────┐     ┌─────────────────────────┐
│  cognition-runtime   │     │ context-refresh-daemon  │
│      (LIVE1A)        │     └─────────────────────────┘
└──────────┬───────────┘
           │ context journal
           ▼
┌──────────────────────┐     ┌─────────────────────────┐
│    paper-manager     │────▶│   timeframe-manager     │
│       (LIVE1B)       │     │  (4TF + Anti-Saw;       │
└──────────┬───────────┘     │   traders STOPPED)      │
           │                 └─────────────────────────┘
           │                 ┌─────────────────────────┐
           ├────────────────▶│  intrabar-supervisor    │
           │                 └─────────────────────────┘
           │                 ┌─────────────────────────┐
           ├────────────────▶│ shadow-stp-be33         │
           ├────────────────▶│ shadow-auction          │
           ├────────────────▶│ shadow-structural       │
           ├────────────────▶│ shadow-eqcorr (ALWAYS)  │
           ├────────────────▶│ trd-outcome2            │
           └────────────────▶│ assurance-runtime       │
                             └─────────────────────────┘
                                      │
           ┌──────────────────────────┼──────────────────────────┐
           ▼                          ▼                          ▼
     ┌───────────┐            ┌──────────────┐          ┌──────────────┐
     │  ops-api  │◀──────────▶│ dashboard-ui │          │ trade-chart  │
     └───────────┘            └──────────────┘          └──────▲───────┘
           ▲                                                   │
           └──────── context-refresher (visual) ───────────────┘

Plane C (sibling compose — not in this file):
  telegram bot + publisher + redis  →  read-only mount of btc_ml_data
```

---

## Plane A — Full model

### 1. collector-watchdog

| Field | Value |
|-------|--------|
| Compose service | `collector-watchdog` |
| Canonical launcher | `collector_watchdog.py --required-only` |
| Entrypoint | `deploy/vps/entrypoints/collector_watchdog.sh` |
| Health evidence | `run/collector_watchdog.pid` alive |
| Network | **Required** (collector children may open market feeds) |
| Write boundary | `data/live/**`, `data/runtime/**`, `/app/run` |

### 2. canonical-runtime

| Field | Value |
|-------|--------|
| Compose service | `canonical-runtime` |
| Canonical launcher | `run.py` |
| Entrypoint | `deploy/vps/entrypoints/canonical_runtime.sh` |
| Health evidence | `run/canonical_runtime.pid` alive |
| Network | As required by runtime hardening / collectors |
| Write boundary | `data/**`, `/app/run`, `/app/logs`, `/app/output` (tmpfs) |

### 3. context-refresh-daemon

| Field | Value |
|-------|--------|
| Compose service | `context-refresh-daemon` |
| Host ctl | `scripts/ops/context_refresh_daemon_ctl.sh` (`foreground`) |
| Canonical launcher | `scripts/live/run_context_refresh_daemon.py --foreground` |
| Entrypoint | `deploy/vps/entrypoints/context_refresh_daemon.sh` |
| Health evidence | `run/context_refresh_daemon.pid` |
| Network | Optional / read local data |
| Write boundary | context artifacts under `data/**`, pid/lock under `/app/run` |
| Notes | Requires `BTC_ML_CONTEXT_REFRESH_DAEMON=1` (set in compose env) |

### 4. cognition-runtime (live1a)

| Field | Value |
|-------|--------|
| Compose service | `cognition-runtime` |
| Canonical launcher | `scripts/live/run_intrabar_cognition_service.py` |
| Entrypoint | `deploy/vps/entrypoints/cognition_runtime.sh` |
| Health evidence | `data/runtime/intrabar_cognition_health.json` (fresh `last_agg` / `last_book`) |
| Network | **Required** (public Binance spot WS) |
| Write boundary | `data/raw_market_events_v2/**`, `data/cognition/intrabar_context_events/**` |

### 5. paper-manager (live1b)

| Field | Value |
|-------|--------|
| Compose service | `paper-manager` |
| Canonical launcher | `scripts/live/run_intrabar_paper_manager.py` |
| Entrypoint | `deploy/vps/entrypoints/paper_manager.sh` (+ `paper_only_guard.py`) |
| Health evidence | `data/deployment/paper_only_contract.json` PASSED + paper health under epoch books / `data/runtime/intrabar_paper_health.json` |
| Network | **Required** (Binance futures BBO/aggTrade for fills) |
| Write boundary | `data/trading/intrabar_paper/<epoch>/**` only for books; never real execution |
| Depends | `cognition-runtime` healthy |

### 6. timeframe-manager

| Field | Value |
|-------|--------|
| Compose service | `timeframe-manager` |
| Canonical launcher | `scripts/live/timeframe_manager_daemon.py --approved-timeframe-manager --paper-only --no-real-execution` |
| Entrypoint | `deploy/vps/entrypoints/timeframe_manager.sh` |
| Health evidence | `run/timeframe_manager.pid` + `data/runtime/timeframe_manager_health.json` |
| Network | Not required beyond local data |
| Write boundary | TF manager health / command bus under `data/**`; **does not** start S4.1 traders |
| Anti-Saw | Inside `TimeframeManager` rails (M15/M30/H1/H4) — not a separate service |

### 7. intrabar-supervisor

| Field | Value |
|-------|--------|
| Compose service | `intrabar-supervisor` |
| Canonical launcher | `scripts/live/intrabar_process_supervisor.py` |
| Entrypoint | `deploy/vps/entrypoints/intrabar_supervisor.sh` |
| Health evidence | `run/intrabar_process_supervisor.pid` + `data/runtime/intrabar_operational_status.json` |
| Network | None required |
| Write boundary | ops status under `data/runtime/**` |

### 8. shadow-stp-be33

| Field | Value |
|-------|--------|
| Compose service | `shadow-stp-be33` |
| Canonical launcher | `scripts/live/run_shadow_stp_be33.py` |
| Entrypoint | `deploy/vps/entrypoints/shadow_stp_be33.sh` |
| Health evidence | `data/trading/shadow_structural_protection/stp_be33/epochs/<epoch>/health.json` with `STP_BE33_RUNNING_SHADOW_ONLY` |
| Network | None required (reads WAL / paper books) |
| Write boundary | `data/trading/shadow_structural_protection/stp_be33/**` only |

### 9. trd-outcome2

| Field | Value |
|-------|--------|
| Compose service | `trd-outcome2` |
| Canonical launcher | `scripts/live/run_trd_outcome2_refresh.py` |
| Entrypoint | `deploy/vps/entrypoints/trd_outcome2.sh` |
| Health evidence | `run/trd_outcome2_refresh.pid` (latest.json under `/app/output` tmpfs may lag) |
| Network | None required |
| Write boundary | `/app/output/audits/trd_outcome2/**` (tmpfs) |

### 10. shadow-auction

| Field | Value |
|-------|--------|
| Compose service | `shadow-auction` |
| Canonical launcher | `scripts/live/run_shadow_auction.py` |
| Entrypoint | `deploy/vps/entrypoints/shadow_auction.sh` |
| Health evidence | `data/trading/shadow_auction/health/health.json` |
| Network | None required |
| Write boundary | `data/trading/shadow_auction/**` only (`storage_mode=repo_local`) |

### 11. shadow-structural

| Field | Value |
|-------|--------|
| Compose service | `shadow-structural` |
| Canonical engine | `StructuralProtectionEngine` |
| Production launcher | `scripts/live/run_shadow_structural_protection.py` (exits if exact history missing) |
| VPS entrypoint | `deploy/vps/entrypoints/shadow_structural.sh` → `shadow_structural.py` with `strict_epoch=False`, `allow_start_without_exact=True` |
| Health evidence | `data/trading/shadow_structural_protection/health.json` (+ policy_manifest); STARTING/DEGRADED OK early |
| Network | None required |
| Write boundary | `data/trading/shadow_structural_protection/**` only |

### 12. shadow-eqcorr (ALWAYS ON)

| Field | Value |
|-------|--------|
| Compose service | `shadow-eqcorr` |
| Canonical engine | `ShadowEconomicCorrelationEngine` |
| VPS entrypoint | `deploy/vps/entrypoints/shadow_eqcorr.py` (`strict_epoch=False`) |
| Health evidence | `data/trading/shadow_economic_correlation/health.json` + `policy_manifest.json` |
| Network | None required |
| Write boundary | `data/trading/shadow_economic_correlation/**` only |
| Profiles | **None** — default stack; never optional |

### 13. assurance-runtime

| Field | Value |
|-------|--------|
| Compose service | `assurance-runtime` |
| Entrypoint | `deploy/vps/entrypoints/assurance_runtime.py` (PID-1 multiplex) |
| Children | `run_shadow_model.py`, `run_behavioral_validation.py`, `run_economic_validation.py`, `run_external_data_toxicity.py`, `run_current_toxicity.py`, `run_incident_correlation.py`, `run_promotion_gate.py`, `run_model_assurance_summary.py` |
| Health evidence | `run/assurance_runtime.pid` + `run/assurance_runtime_status.json`; child health under `data/model_assurance/**/runtime/health.json` |
| Network | None required (local artifacts) |
| Write boundary | `data/model_assurance/**` only |
| Exit policy | SIGTERM multiplex; exits if any critical child dies |

---

## Plane B — Ops surface

### 14. ops-api

| Field | Value |
|-------|--------|
| Compose service | `ops-api` |
| Canonical launcher | `dashboard/backend/run_api.py` |
| Health evidence | HTTP `GET /health` |
| Network | Host publish `${OPS_API_HOST_PORT:-18080}` → `8080` |
| Write boundary | Prefer read of `/app/data`; may write ops caches under data if configured |

### 15. dashboard-ui

| Field | Value |
|-------|--------|
| Compose service | `dashboard-ui` |
| Image | `deploy/vps/docker/dashboard-ui.Dockerfile` |
| Health evidence | HTTP `GET /` |
| Network | Host publish `${DASHBOARD_UI_HOST_PORT:-15173}` → `80` |
| Write boundary | None (static nginx) |

### 16. context-refresher (visual)

| Field | Value |
|-------|--------|
| Compose service | `context-refresher` |
| Canonical launcher | `scripts/live/run_market_context_visual_refresher.py` |
| Entrypoint | `deploy/vps/entrypoints/context_refresher.sh` |
| Health evidence | `run/context_visual_refresher.pid` + `apps/context_visualizer/public/data/visual_status.json` |
| Network | None required |
| Write boundary | named volume `visual_public_data` → `/app/apps/context_visualizer/public/data`; research under `data/research/**` |

### 17. trade-chart

| Field | Value |
|-------|--------|
| Compose service | `trade-chart` |
| Canonical launcher | `python -m http.server 8765` on `apps/context_visualizer/public` |
| Entrypoint | `deploy/vps/entrypoints/trade_chart.sh` |
| Health evidence | HTTP `GET /` on `:8765` |
| Network | Host publish `${TRADE_CHART_HOST_PORT:-18765}` → `8765` |
| Write boundary | Read-only serve; shares `visual_public_data` volume |

---

## Plane C — Telegram (sibling)

| Field | Value |
|-------|--------|
| Compose | **Not** in `deploy/vps/docker-compose.yml` |
| Operator | `./scripts/deploy/vps_telegram.sh` → sibling `../btc-ml-telegram-bot` |
| Services | bot + publisher + redis (+ state-init) |
| Data | Publisher **read-only** mount of `btc_ml_data` |
| Project | `btcml-telegram` (blast-radius isolation) |

---

## Plane D — Hyperliquid vault (optional profile)

Not part of the paper-only full model. Opt-in via compose profile `hl-vault-testnet`.
Does **not** share the paper-manager process or `paper_only_guard`.

| Field | Value |
|-------|--------|
| Compose service | `hl-vault-executor` |
| Profile | `hl-vault-testnet` (default stack stays paper-only) |
| Canonical launcher | `scripts/live/run_hl_vault_executor.py` |
| Entrypoint | `deploy/vps/entrypoints/hl_vault_executor.sh` (+ `hl_vault_guard.py`) |
| Health evidence | `data/deployment/hl_vault_contract.json` PASSED + `data/trading/hyperliquid_vault/health.json` |
| Network | **Required** (Hyperliquid testnet `/info` + `/exchange`) |
| Write boundary | `data/trading/hyperliquid_vault/**` only |
| Secrets | `HL_TESTNET_AGENT_PK` + `HL_VAULT_ADDRESS` on this service only; paper-manager forbids those env vars |
| Mainnet | Refused unless `HL_MAINNET_ENABLED=true` and `config/hl_vault_mainnet.json` |

---

## Bootstrap (profile only)

| Field | Value |
|-------|--------|
| Compose service | `vps-bootstrap` |
| Profile | `bootstrap` (not long-running) |
| Script | `scripts/deploy/bootstrap_vps_environment.py` |
| Tag | `VPS_DEPLOYMENT_TAG=VPS_DEPLOY` |
| Safety | Refuses Mac live `data/` path; paper-only epoch via `create_epoch` / `activate_epoch` |

---

## Paper-only contract

| Mechanism | Names enforced |
|-----------|----------------|
| Config | `config/intrabar_paper_execution.json` → `paper_only`, `real_execution_enabled` |
| Guard | `deploy/vps/entrypoints/paper_only_guard.py` → `data/deployment/paper_only_contract.json` |
| TF manager | `--paper-only --no-real-execution` |
| Env mirrors | `PAPER_ONLY=true`, `REAL_EXECUTION_ENABLED=false`, `EXECUTION_ENABLED=false` |

---

## Volumes

| Volume | Mount | Writers |
|--------|-------|---------|
| `btc_ml_data_vps` | `/app/data` | Plane A (+ bootstrap) |
| `btc_ml_visual_public_vps` | `/app/apps/context_visualizer/public/data` | context-refresher |
| tmpfs `/app/run`, `/tmp`, `/app/logs`, `/app/output` | per runtime service | PIDs / logs / audits |
