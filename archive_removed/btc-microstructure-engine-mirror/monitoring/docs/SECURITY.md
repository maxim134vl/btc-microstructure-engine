# Security

## 1. Threat model (STRIDE)

| Threat | Vector | Mitigation | Status |
| --- | --- | --- | --- |
| **Spoofing** of UI/API access | Internet-facing dashboard | Traefik basic-auth (`bcrypt` htpasswd) at edge; per-route middlewares | MVP |
| **Spoofing** identity inside cluster | One service impersonates another | Docker networks isolate; future mTLS via SPIRE | v0.3 |
| **Tampering** with parquet store | Compromised obs container writes to /data | All obs mounts of `/data` are **read-only** (`:ro` flag enforced in compose) | MVP |
| **Tampering** with metrics | Forged push to Prometheus | Prom is pull-only; no `/api/v1/admin/tsdb/snapshot` exposed | MVP |
| **Repudiation** of restart actions | "Who restarted the collector?" | watchdog emits structured audit-log to Loki with `actor=watchdog`, `correlation_id`, `target_container`, `reason` | MVP |
| **Information disclosure** of secrets | Secrets in env vars visible to `docker inspect` | Use `_FILE` env var pattern + Docker secrets in swarm; `.env` permissions `600`; CI scan with `gitleaks` | MVP (dev), v0.2 (prod) |
| **Information disclosure** in logs | Tokens / IPs / API keys printed | Structured logger with `REDACT` filter (regex over known keys) | MVP |
| **DoS** of dashboard | HTTP flood, WS storms | Traefik `RateLimit` middleware (10 rps/IP burst 20); WS connection cap (200/replica) | MVP |
| **DoS** of Prometheus | High-cardinality label explosion from exporter | Cardinality limit in `prometheus.yml` (`sample_limit: 10000`, `label_limit: 30`) | MVP |
| **Elevation of privilege** via docker socket | Compromise of any container → `docker.sock` → host | docker socket **never** mounted in collectors/pipeline/health-api. watchdog accesses it only via `tecnativa/docker-socket-proxy` with allowlist `CONTAINERS=1, POST=1` | MVP |
| **Elevation of privilege** inside image | Container exploit → root in container → kernel | All custom services run as UID `10001`, no shell in prod variant, no `CAP_*` granted, `read_only: true` rootfs where possible | MVP |

## 2. Hardening checklist

### Per-image
- [x] Non-root user (`USER 10001`)
- [x] Pinned base image with explicit SHA in CI (`@sha256:...` once promoted)
- [x] Multi-stage build, no compilers in runtime layer
- [x] No `latest` tags in any production manifest
- [x] `HEALTHCHECK` directive defined
- [x] `dumb-init` or `tini` as PID 1 for proper signal handling
- [x] `.dockerignore` excludes `.env`, `*.pem`, `*.key`

### Per-container
- [x] `read_only: true` for stateless services (with `tmpfs` for needed writable paths)
- [x] `cap_drop: [ALL]`, only required capabilities added back
- [x] `security_opt: [no-new-privileges:true]`
- [x] CPU + memory limits set
- [x] Restart policy `unless-stopped` (dev) / `on-failure: 5` (prod)
- [x] Logging driver with rotation (`max-size: 10m`, `max-file: 3`)

### Per-network
- [x] All inter-service traffic on internal Docker networks
- [x] Only Traefik publishes host ports
- [x] No `host` network mode anywhere
- [x] No `--privileged` containers (cAdvisor uses fine-grained read-only mounts)

### Secrets
- [x] `.env` is gitignored; example file uses obviously-fake placeholders
- [x] Bootstrap script (`scripts/bootstrap.sh`) regenerates htpasswd + self-signed certs
- [ ] Vault integration (v1.0)
- [x] In Swarm: `docker secret create ...` then bind-mount; never env-var pass

### TLS
- [x] Traefik terminates TLS at edge; HTTPS-only redirects from HTTP
- [x] Self-signed certs in dev (CN=localhost); real ACME (Let's Encrypt) in prod
- [ ] mTLS between services (v0.3 — config stub already in `infra/traefik/dynamic.yml`)

### Audit
- [x] Every watchdog action logged to Loki with: timestamp, actor, action, target, reason, correlation_id
- [x] Every Traefik request logged in JSON with method, path, status, latency, user (when basic-auth)
- [ ] Tamper-evident audit (v1.0 — append-only or signed)

## 3. Secrets handling

### Dev
```bash
# .env file, mode 0600
cp .env.example .env
chmod 600 .env
# fill in TRAEFIK_DASHBOARD_AUTH, MONITOR_UI_AUTH, etc.
```

### Prod (Swarm)
```bash
echo -n "supersecret" | docker secret create grafana_admin_password -
# then in stack file:
#   secrets: [grafana_admin_password]
#   environment:
#     GRAFANA_ADMIN_PASSWORD_FILE: /run/secrets/grafana_admin_password
```

All services support the `_FILE` convention (read secret from file). See `scripts/swarm-secrets.sh`.

### Future (v1.0)
Vault Agent sidecar — fetches at start, refreshes via signal. The `_FILE` env pattern is already compatible.

## 4. RBAC (roadmap)

| Role | Endpoints | Implementation |
| --- | --- | --- |
| `viewer` | monitor-ui, grafana (read-only) | basic-auth → `X-Forwarded-User` |
| `operator` | + watchdog actions, AM silences | OIDC group claim via traefik-forward-auth |
| `admin` | + prometheus admin, traefik dashboard | OIDC + sudo claim |

MVP is single-tier (basic-auth). RBAC is v0.4.

## 5. Supply chain

- CI workflow (`ci/github/workflows/security-scan.yml`) runs Trivy on every PR
- `make scan` runs Trivy locally
- Future: cosign signature verification at runtime (v0.2)
- Future: SBOM generation per image (v0.2)

## 6. Compliance posture

- All authentication events logged.
- All actor-action pairs logged.
- 7-day log retention by default (Loki); operator can extend to 90d.
- No PII in metrics by design (no user-identifiable data flows through obs plane).

## 7. Incident reporting

Security incident? Tag the PR with `security` label, page on-call (see [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) §security-incidents), do **not** push fixes through normal CI.
