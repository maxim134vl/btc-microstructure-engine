# Services

Per-service responsibility, dependencies, ports, and APIs.

## metrics-exporter

**Purpose**: Domain telemetry collection from the data-plane (parquet store).
**Stack**: Python 3.12, `aiohttp`, `prometheus_client`, `pyarrow`.
**Reads**: `/data/*.parquet` (read-only).
**Writes**: nothing on disk; in-memory metric registry only.
**Exposes**: `:9101/metrics` (Prometheus), `:9101/healthz`.
**Critical**: yes.

Configuration via env vars (`config.py`):

- `METRICS_EXPORTER_SCAN_INTERVAL_SECONDS` (default 10)
- `METRICS_EXPORTER_FEATURE_SAMPLE_ROWS` (default 2000)
- `LOG_LEVEL`

Collectors live in `src/collectors/`:
- `parquet_scanner.py` — file freshness, schema validity, growth rate
- `runtime_probe.py` — parses runtime log file to derive iteration age
- `feature_health.py` — NaN/inf ratio, z-score stats per feature
- `regime_distribution.py` — last-N histogram of categorical regimes

---

## health-api

**Purpose**: Domain-aware health aggregation + UI server + WebSocket fanout.
**Stack**: Python 3.12, FastAPI, `uvicorn`, `httpx`, `redis-py`.
**Reads**: Prometheus query API (`http://prometheus:9090`), Redis pubsub.
**Writes**: nothing persistent.
**Exposes**: `:8080/api/health/*`, `:8080/ws`, `:8080/healthz`, plus static assets at `/`.
**Critical**: yes.

REST routes (under `/api`):

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/health`                       | overall { status, ts, domains[] } |
| GET | `/api/health/pipeline`              | pipeline domain detail |
| GET | `/api/health/dataflow`              | per-parquet freshness/growth |
| GET | `/api/health/feed`                  | per-feed lag/reconnects |
| GET | `/api/health/system`                | host CPU/mem/disk |
| GET | `/api/health/research`              | feature drift + regime distribution |
| GET | `/api/alerts/active`                | currently firing alerts |
| GET | `/api/alerts/history?since=ISO8601` | last N alerts |
| GET | `/api/services`                     | container inventory + state |

WebSocket:

| Path | Subscriptions |
| --- | --- |
| `/ws` | client sends `{op:"sub", topic:"alerts.live"\|"health.tick"}` |

UI is served from `/` (static SPA bundle).

---

## alert-engine

**Purpose**: Alertmanager webhook receiver. Applies dedup, cooldown, severity escalation. Persists active alerts in Redis. Publishes to `alerts.live` pubsub channel for health-api fanout.

**Stack**: Python 3.12, `aiohttp`, `redis-py`.
**Reads**: Alertmanager webhook payloads, Redis state.
**Writes**: Redis keys with TTL.
**Exposes**: `:9102/webhook`, `:9102/healthz`, `:9102/metrics`.
**Critical**: yes.

Webhook contract (Alertmanager v4):
```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"…\"}",
  "status": "firing",
  "alerts": [{"labels": {...}, "annotations": {...}, "startsAt": "…"}]
}
```

Redis keys:
- `alert:active:<fingerprint>`   — JSON, TTL=expiry+cooldown
- `alert:cooldown:<fingerprint>` — boolean flag, TTL=cooldown
- `alert:history:<YYYYMMDD>`     — ZSET ts→fingerprint

---

## watchdog

**Purpose**: Self-healing layer. Detects dead/stalled containers via Prometheus query; issues `docker restart` via socket-proxy. Enforces restart budget.

**Stack**: Python 3.12, `httpx`, `docker` (python SDK), connects to `tcp://socket-proxy:2375`.
**Reads**: Prometheus query API.
**Writes**: docker actions (restart only).
**Exposes**: `:9103/healthz`, `:9103/metrics`, `:9103/api/audit?since=...`.
**Critical**: no (manual restart possible).

Policies (`src/policies.py`):
- **stall-detect**: if `btc_runtime_last_iter_age_seconds > WATCHDOG_STALL_THRESHOLD_SECONDS` for 2 min → restart pipeline
- **dead-collector**: if `up{job=~"collector.*"} == 0` for 90s → restart that collector
- **reconnect-storm**: if `rate(btc_feed_reconnects_total[5m]) > N` → trip circuit; cool off 15 min; alert

Restart budget: `WATCHDOG_RESTART_BUDGET_PER_HOUR=10`. Beyond budget → skip + emit `audit.container.skip`.

---

## monitor-ui

**Purpose**: Dense engineering dashboard. Vite + TypeScript + lit-html. ~30 KB gz. No business logic.

**Build artifact**: `services/monitor-ui/dist/` is volume-mounted into health-api's `/app/static`.

UI panels:

1. **Top bar**: 7 status pills — system / feed / runtime / data / features / alerts / errors
2. **Pipeline Health**: iter age sparkline, runtime uptime, restart count
3. **Data Flow**: table of parquet files with age/size/growth/schema columns
4. **Live Feed**: per-feed reconnect rate, lag, last-msg age
5. **System Health**: CPU/mem/disk gauges + zombie process count
6. **Research**: feature drift heatmap (compact), regime stack bar
7. **Alert Center**: live-updating list of active alerts with severity, cooldown TTL, ack button

WebSocket-driven. No polling.

---

## Vendor services

- **prometheus** (`:9090` internal): TSDB, scrape, evaluate rules
- **alertmanager** (`:9093` internal): route alerts to alert-engine webhook
- **loki** (`:3100` internal): log store
- **promtail** (`:9080` internal): log shipper, mounts host `/var/lib/docker/containers` ro
- **grafana** (`:3000` internal): deep-dive dashboards
- **cadvisor** (`:8080` internal): container telemetry; mounts `/sys`, `/var/run`, `/var/lib/docker` ro
- **node-exporter** (`:9100` internal): host telemetry; mounts `/`, `/proc`, `/sys` ro with `--path.rootfs=/host`
- **redis** (`:6379` internal): alert state + pubsub
- **socket-proxy** (`:2375` internal): docker.sock gateway with allowlist
- **traefik** (`:80`, `:443` host): edge proxy

## Inter-service dependency graph

```
monitor-ui ── http ──▶ health-api ── http ──▶ prometheus ──▶ scrapes everywhere
                          │  pubsub
                          ▼
                       redis ◀── pubsub publish ── alert-engine ◀── webhook ── alertmanager
                                                                                ▲
                                                                                │ rule eval
                                                                                │
                                                                          prometheus
                          ▲
                          │ http audit query
                          │
                       watchdog ── http ──▶ socket-proxy ── docker.sock ──▶ host docker
```
