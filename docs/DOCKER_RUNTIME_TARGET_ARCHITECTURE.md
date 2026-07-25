# Docker Runtime Target Architecture

**Status:** specification only (Patch 2A.1)
**Implementation:** not started — no Dockerfile / Compose in this patch

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
docker compose up
```

### Persistent volumes (future)

```text
model-data
model-runtime-state
paper-ledger
```

### Environment (future)

```text
BTC_ML_ROOT
BTC_ML_DATA_ROOT
BTC_ML_LOG_LEVEL
BTC_ML_RUNTIME_MODE
BTC_ML_CONTEXT_REFRESH_DAEMON
```

### Write-plane rule

Only `model-runtime` may write authoritative model/context/decision/paper datasets.
`ops-dashboard` and `trade-chart` are read-only consumers.
