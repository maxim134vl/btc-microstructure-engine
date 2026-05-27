# Scaling

## 1. What scales horizontally

| Service | Stateless? | Replicas safe? |
| --- | --- | --- |
| traefik          | yes (in Swarm mode) | yes |
| health-api       | yes (state in Redis) | yes |
| metrics-exporter | yes  | **but** scraping logic is idempotent — only one *should* run per data partition; Prometheus deduplicates if needed |
| alert-engine     | yes (state in Redis) | yes |
| watchdog         | **no** — actions must serialize; use `replicas: 1` + Swarm leader election or a lock in Redis |
| monitor-ui       | static — Traefik serves any replica |
| grafana          | stateless if Postgres backend used; SQLite single-replica |

## 2. What does NOT scale horizontally

| Service | Why | Mitigation |
| --- | --- | --- |
| prometheus  | TSDB is per-instance | Federation OR migrate to VictoriaMetrics (cluster mode) |
| loki        | filesystem TSDB is per-instance | S3 backend + microservice mode |
| redis       | single-leader | Redis Sentinel (3 nodes) for HA; Cluster for sharding |

## 3. Stateful services in Swarm

Pin to specific nodes via labels:

```yaml
deploy:
  placement:
    constraints:
      - node.labels.role == storage
```

Volume strategy:
- **Local volume** (default) — bound to a single node; rescheduling = data loss
- **NFS / CSI volume** — shared across nodes; required for true HA

For prod, use a CSI driver:
- AWS: EBS CSI (single-zone) or EFS CSI (multi-zone)
- on-prem: Longhorn, Portworx

## 4. Capacity planning

### Prometheus

```
series_count   * sample_size_bytes / scrape_interval = bytes/sec
```

With ~50k series at 30s scrape: ~3 MB/s sustained, ~250 GB / 30d.
With 15d retention + 10 GB cap, we serve up to ~30k active series comfortably.

Scale path:
1. Raise `PROMETHEUS_RETENTION_SIZE` (single-node, more disk)
2. Federate: a "long-term" Prom scrapes the operational Prom at 60s intervals
3. Migrate to VictoriaMetrics single-node (drop-in)
4. VictoriaMetrics cluster (vmselect/vminsert/vmstorage)

### Loki

`ingestion_rate_mb`, `ingestion_burst_size_mb` in `loki-config.yml`. Filesystem
TSDB scales to ~50 GB before query times degrade. S3 backend removes that limit.

### Custom services

CPU/mem profile (steady-state, no load):

| Service          | CPU | Mem  |
| ---              | --- | ---  |
| metrics-exporter | 50 mCPU | 80 MB |
| health-api       | 50 mCPU | 120 MB |
| alert-engine     | 20 mCPU | 60 MB |
| watchdog         | 20 mCPU | 60 MB |
| monitor-ui       | (static) | — |

These fit on a 1 vCPU / 2 GB node easily. The bottleneck at scale is always
Prometheus or Loki, never the custom services.

## 5. Geographic distribution

Out of scope for v0.1. Sketch for v1.0:

- Engine in one region (close to exchange WS endpoints)
- Observability stack mirrored per-region with federated Prom + S3-backed Loki
- Single global Alertmanager cluster (gossip mode, 3 replicas)

## 6. Disaster recovery

| Asset | RPO | RTO | Strategy |
| --- | --- | --- | --- |
| Engine parquet store | 60s (live feeds re-collect) | 5 min | Replay from upstream |
| Prometheus TSDB | 24h | 30 min | Daily snapshot to S3 |
| Loki chunks | 24h | 30 min | S3 backend = inherent backup |
| Redis state | 0 (ephemeral) | 0 | Just restart |
| Configs | 0 | < 1 min | Git |

DR procedure (single-region recovery):
1. Restore Prometheus snapshot to a new host
2. `make swarm-deploy`
3. Engine replays from upstream collectors
4. Loki picks up new logs immediately

## 7. Cost model (single-region prod)

| Component | Instance | Monthly |
| --- | --- | --- |
| 1× compute node (4 vCPU, 8 GB) | c6i.xlarge | ~$120 |
| 1× storage node (2 vCPU, 16 GB, 500 GB) | r6i.large + EBS | ~$130 |
| 1× edge (Traefik + monitor-ui) | t3.small | ~$15 |
| Bandwidth | — | ~$10 |
| **Total** | | **~$275/mo** |

(Bare-metal equivalents ~30% cheaper; managed Prom/Loki SaaS ~2× more.)
