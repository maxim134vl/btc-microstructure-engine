# Docker Runtime Target Architecture

**Status:** implemented for production-like local cold-start
**Implementation:** root `compose.yaml`, `docker/Dockerfile.runtime`, and `scripts/btc-ml-stack`

Future packaging exposes **three** top-level Compose services. Operators interact with these entities, not with every child process.

---

## Service 1 — `model-runtime`

Internal components (one user-facing service, multiple child processes):

- live market feed
- feed watchdog / supervisor
- canonical pipeline (`run.py`)
- dedicated context refresher
- lifecycle writers (via shared context builders)
- decision logger
- later: paper controller (only when Patch 2B+ explicitly allows)

Canonical launch:

```bash
docker compose up model-runtime
```

Logs:

```bash
docker compose logs -f model-runtime
```

Host-era control target (spec only in 2A.1; supervisor not implemented here):

```bash
scripts/ops/model_runtime_ctl.sh foreground
```

`foreground` requirements (future):

- remain PID 1 or run under a proper init
- multiplex component logs to stdout
- on SIGTERM: stop children cleanly, no zombies, clear PID/locks
- non-zero exit on critical model failure

---

## Service 2 — `ops-dashboard`

Reads:

- runtime dataset status
- metadata sidecars
- process health
- freshness
- writer status
- errors
- engine registry

Must **not**:

- write cognition parquet
- write context / lifecycle
- create decisions
- start trades

```bash
docker compose up ops-dashboard
docker compose logs -f ops-dashboard
```

---

## Service 3 — `trade-chart`

Read-only visualization:

- price
- market contexts
- lifecycle episodes
- context origin
- entries / exits
- signals / orders / paper trades
- P&L

```bash
docker compose up trade-chart
docker compose logs -f trade-chart
```

---

## All services

```bash
scripts/btc-ml-stack start
```

### Persistent host mounts

```text
./data -> /app/data
./run  -> /app/run
./logs -> /app/logs
./     -> /app (model-runtime only; preserves legacy root-level parquet state)
```

### Environment

```text
BTC_ML_ROOT
BTC_ML_DATA_ROOT
BTC_ML_LOG_LEVEL
BTC_ML_RUNTIME_MODE
BTC_ML_CONTEXT_REFRESH_DAEMON
```

The container boot boundary clears stale PID/lock files and archives only
`data/runtime/intrabar_supervision_state.json` with a timestamped name. Paper
epochs, WAL, books, positions, trades, sizing and economics data are never reset.

`model-runtime` has separate liveness and readiness contracts. Liveness accepts
`STARTING` and demonstrably progressing LIVE1B `RECOVERING`; readiness requires
LIVE1B `HEALTHY`, both execution streams fresh, `unresolved_gap=false`,
`entry_allowed=true`, zero WAL write failures, and the paper-only safety flags.
Recovery has a 180 second initial grace, a 180 second no-progress timeout, and a
3600 second absolute upper bound. A changing LIVE1B health timestamp or advancing
execution-market checkpoint is progress. The intrabar supervisor and STP start
only after LIVE1A is ready and LIVE1B recovery has completed.

The Telegram bot remains a separate Compose project.
The start wrapper refuses to run while host-era BTC-ML writers are alive, which
prevents duplicate collectors or ledger writers during the one-time migration.

### Write-plane rule

Only `model-runtime` may write authoritative model/context/decision/paper datasets.
`ops-dashboard` and `trade-chart` are read-only consumers.
