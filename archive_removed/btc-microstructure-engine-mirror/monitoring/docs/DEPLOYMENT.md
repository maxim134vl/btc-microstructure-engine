# Deployment

Three supported modes. All share the same images and configs; only the
compose-file layering changes.

## Mode 1 — Dev (single host, defaults)

```bash
cd monitoring/
make init       # bootstraps .env + self-signed certs + htpasswd
make build
make up
```

Compose layering:
```
docker-compose.yml                     (engine, existing)
deploy/docker-compose.monitoring.yml   (obs stack)
deploy/docker-compose.dev.yml          (dev overrides: relaxed limits, exposed ports)
```

What "dev" implies:
- TLS via self-signed cert (CN=localhost)
- Resource limits commented out
- `:9090` etc. published to host loopback for direct CLI access
- Promtail tails Docker logs via socket
- Grafana anonymous viewer enabled (read-only)

Verify:
```bash
make smoke      # asserts /metrics, /healthz, /api/health respond
```

## Mode 2 — Single-node prod hardened

Same host, hardened layering:
```
docker-compose.yml + monitoring.yml + docker-compose.prod.yml
```

What "prod" implies on top of dev:
- `ENVIRONMENT=prod`
- Resource limits enforced (CPU/mem)
- `read_only: true` + tmpfs on stateless containers
- `cap_drop: [ALL]`, `no-new-privileges`
- No published ports except `:80`, `:443` (Traefik)
- Real ACME / Let's Encrypt cert
- Grafana anonymous disabled

```bash
ENVIRONMENT=prod make build
ENVIRONMENT=prod make up
```

## Mode 3 — Swarm (multi-node, HA)

```bash
make swarm-init     # docker swarm init + secret materialization
make swarm-deploy   # docker stack deploy ...
```

Stack files:
```
deploy/swarm/stack-engine.yml         engine services
deploy/swarm/stack-monitoring.yml     obs stack
```

What changes for Swarm:
- Replicas: `health-api`, `metrics-exporter`, `alert-engine` set to `replicas: 2` with `placement.constraints` to spread across nodes
- Prometheus and Loki pinned to a node with persistent volumes (`placement.constraints: [node.labels.role == storage]`)
- Secrets via `docker secret`, never env vars
- Traefik in Swarm mode auto-discovers replicas via service labels
- Healthchecks tighter (faster failover)

### Node labeling
```bash
docker node update --label-add role=storage    <storage-node>
docker node update --label-add role=compute    <compute-node>
```

### Persistent volumes
Prometheus and Loki use named volumes pinned to the storage node. For multi-node
HA storage, use a CSI driver (Longhorn / Portworx / cloud-native EBS). See
[SCALING.md](SCALING.md#stateful-services).

## Bootstrap script (`scripts/bootstrap.sh`)

Steps it performs:
1. Verifies docker + docker compose v2 are installed
2. Copies `.env.example` → `.env` (if missing)
3. Generates self-signed TLS pair into `infra/traefik/certs/` (skipped in prod)
4. Generates bcrypt htpasswd entries if `TRAEFIK_DASHBOARD_AUTH` is unchanged
5. Prints next steps

Idempotent. Re-running won't regenerate existing files.

## Upgrading

1. Pull image versions you want via `.env` (`PROMETHEUS_VERSION=...`)
2. `make build`
3. Rolling restart: `make restart-svc SVC=<name>` per service
4. Verify each before moving on: `make smoke`

Never `up -d` everything during an upgrade — restarts in groups.

## Downgrading

The reverse, plus:
- Prometheus TSDB is forward-compatible across minor versions but **not** across major. Major-version downgrade requires data deletion.
- Loki TSDB is similar.

For safe rollbacks, snapshot the TSDB before upgrade:
```bash
docker exec prometheus wget -qO- --post-data=                                  \
   http://localhost:9090/api/v1/admin/tsdb/snapshot
```

(Note: admin API is disabled by default. Re-enable temporarily for snapshot.)

## Multi-region / DR

Out of scope for v0.1. See [SCALING.md §dr](SCALING.md#disaster-recovery).
