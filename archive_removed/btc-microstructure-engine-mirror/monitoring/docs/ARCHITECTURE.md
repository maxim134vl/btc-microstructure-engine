# Architecture

## 1. Design principles

| Principle | Concretely |
| --- | --- |
| **Plane separation** | Data-plane (collectors / runtime / parquet) and observability-plane never share state. Killing obs cannot kill engine. |
| **Pull over push** | Prometheus pulls all metrics. No metric depends on the producer's reachability of a central server. |
| **Filesystem as source of truth** | `/data/*.parquet` is the canonical observable. metrics-exporter stats files; it does not depend on the producers being reachable. |
| **Read-only by default** | All observability containers mount `/data` read-only. Only the watchdog has any write authority (and only via socket-proxy with `POST=1`, `CONTAINERS=1`). |
| **Stateless services** | health-api, alert-engine, metrics-exporter all stateless. State lives in Redis (alerts) and Prometheus (TSDB). |
| **Network segmentation** | Three Docker networks: `dataplane`, `obsplane`, `edge`. Cross-plane traffic only through narrow, explicit links. |
| **No business logic in UI** | monitor-ui is a dumb terminal. All aggregation/severity in health-api. |

## 2. Topology

```
                              ┌──── Traefik (edge) ────┐
                              │  TLS · authn · ratelimit│
                              └────────┬───────────────┘
                                       │
              ┌────────────┬───────────┼───────────┬──────────────┐
              ▼            ▼           ▼           ▼              ▼
          monitor-ui   health-api   Grafana   Prometheus     Alertmanager
                          │ WS         │           │              │
                          │            │           │              │
              ┌───────────┴────────┐   │           │              │
              ▼                    ▼   ▼           │              │
            Redis              Prometheus query    │              │
              ▲                                    │              │
              │            ┌───────────────────────┴──────────────┘
              │            │       scrape
              │            ▼
              │   ┌──────────────────────────────────────────────┐
              │   │ metrics-exporter   node-exporter   cAdvisor  │
              │   │  (custom)                                    │
              │   └──────────┬───────────────────────────────────┘
              │              │
              │              │ stat() readonly
              │              ▼
              │       /data/*.parquet  ◀── collectors (engine)
              │
              │
              │       ┌─── Loki ◀── Promtail ◀── docker logs
              │       │
              │       └── queried by Grafana + health-api
              │
              └─◀── alert-engine ◀── webhook ◀── Alertmanager
                       │
                       └─── docker-socket-proxy ◀── watchdog
```

## 3. Networks

| Network | Members | Direction allowed |
| --- | --- | --- |
| `edge`     | traefik, health-api, grafana, prometheus, alertmanager | inbound from internet via traefik only |
| `obsplane` | prometheus, alertmanager, loki, promtail, grafana, redis, metrics-exporter, health-api, alert-engine, watchdog, cadvisor, node-exporter, socket-proxy | internal only |
| `dataplane` | engine services (collectors, pipeline), **metrics-exporter** *(joined for parquet read-only mount)*, **promtail** *(joined for log discovery)* | internal only |

metrics-exporter and promtail straddle two networks — minimum necessary to bridge the planes. Nothing else does.

## 4. Image strategy

- **Vendor services** pinned by SHA-able tag (`prom/prometheus:v2.55.1`, `grafana/grafana:11.3.0`, etc.). See `.env.example` for the full list.
- **Custom services** built from `services/<name>/Dockerfile`. Multi-stage: builder layer → distroless-or-slim runtime. UID `10001`, no shell in prod variant.
- **One image per service**. No "shared everything" image — that pattern exists in the engine subtree because the engine code is monolithic, but observability services have small, distinct dependency footprints.

## 5. Service boundaries (DDD-ish)

```
        ┌─────────────────────── domain ───────────────────────┐
        │                                                       │
        │  PipelineHealth     DataFreshness    FeedHealth      │
        │  SystemHealth       FeatureHealth    AlertCenter     │
        │                                                       │
        └────────────┬──────────────────────┬───────────────────┘
                     │                      │
        ┌────────────▼──────────────┐  ┌────▼────────────────┐
        │ metrics-exporter           │  │ health-api         │
        │  - parquet_scanner         │  │  - aggregators     │
        │  - runtime_probe           │  │  - REST            │
        │  - feature_health          │  │  - WS fanout       │
        │  - regime_distribution     │  │  - static serve UI │
        └────────────────────────────┘  └────────────────────┘

        ┌──────────────────────────┐    ┌─────────────────────┐
        │ alert-engine              │   │ watchdog            │
        │  - webhook intake         │   │  - liveness probe   │
        │  - cooldown / dedup       │   │  - restart policy   │
        │  - severity routing       │   │  - circuit breaker  │
        │  - redis state + pubsub   │   │  - audit log        │
        └──────────────────────────┘    └─────────────────────┘
```

## 6. Data flow (end-to-end)

**Metric**:
```
collector writes parquet → metrics-exporter scans on tick →
exposes /metrics → prometheus scrapes → rule fires →
alertmanager groups+dedups → webhook → alert-engine →
redis SETEX cooldown key → publish on pubsub →
health-api ws fanout → monitor-ui panel turns red
```

End-to-end alert latency target: **< 30s** in dev, **< 15s** in prod.

**Log**:
```
container stdout → docker json-file driver → promtail tail →
loki push → grafana query / health-api log preview
```

## 7. Failure modes

| Failure | Behavior |
| --- | --- |
| Prometheus down | Alerts stop firing, but metrics-exporter keeps running; UI shows "Prometheus unreachable" panel; engine is unaffected |
| Loki down | Logs lost during outage; metrics unaffected; UI log preview unavailable |
| Redis down | Alert dedup degrades to "no dedup" (every fire becomes an event); UI still receives via direct AM webhook |
| Watchdog down | No auto-recovery; humans must intervene; everything else healthy |
| docker-socket-proxy down | Watchdog actions fail closed; no spurious restarts |
| metrics-exporter down | Domain metrics stop updating; cAdvisor + node-exporter still feed Prometheus so container/system metrics continue |
| health-api down | UI unavailable; everyone else unaffected; restart |
| Traefik down | All edge endpoints unreachable; internal scraping continues |

No single observability failure can degrade the engine. Verified by network topology.

## 8. Scaling axes

| Axis | Strategy | Where |
| --- | --- | --- |
| Metrics volume | Vertical (PROMETHEUS_RETENTION_SIZE) → federation → VictoriaMetrics | `infra/prometheus/` |
| Log volume | Vertical → Loki S3 backend → Mimir | `infra/loki/` |
| Custom service throughput | Horizontal (Swarm `replicas: N`) — all are stateless | `deploy/swarm/` |
| WS fan-out | health-api has no shared state; sticky-session via traefik OR Redis pubsub bridges replicas | `services/health-api/` |

See [SCALING.md](SCALING.md).

## 9. Roadmap

See `README.md §Roadmap` (mirrored to the top-level architecture narrative).

## 10. Decision log

- **Prometheus vs VictoriaMetrics** → Prom now, VM at v0.3 if retention bites
- **ELK vs Loki** → Loki: label model matches Prom, ~10× cheaper at our log volume
- **React vs lit-html** → lit-html: smaller bundle (~30 KB), no framework taxes for a dashboard with ~6 panels
- **Native Streamlit reuse vs new UI** → Streamlit is fine for research; ops needs WS, sub-second updates, dense panels — Streamlit can't do it
- **k8s vs Swarm** → Swarm for v1.0; the existing engine compose can be `docker stack deploy`-ed with two-line edits. k8s migration via Kompose at v1.0 if multi-region needed.
