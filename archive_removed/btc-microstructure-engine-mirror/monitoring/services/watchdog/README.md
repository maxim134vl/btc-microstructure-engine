# watchdog

Self-healing layer. Polls Prometheus, applies decision policies, executes
restart actions through docker-socket-proxy. Strict allowlist + budget +
circuit breaker. Audit log of every action.

## Policies (MVP)

| Policy | When it fires | Action |
| --- | --- | --- |
| `stall-detect` | `max(btc_runtime_last_iter_age_seconds) >= WATCHDOG_STALL_THRESHOLD_SECONDS` | restart `btc_pipeline` |
| `reconnect-storm` | per-feed `rate(btc_feed_reconnects_total[5m]) >= threshold` | trip circuit breaker (auto-closes after cooloff) |

`dead-collector` policy stub is present in `policies.py` but disabled in
the orchestrator until container↔scrape-target mapping is wired (v0.2).

## Safety

- **Allowlist**: restart only containers whose name starts with one of
  `RESTART_ALLOWLIST` patterns. Anything else is logged + skipped.
- **Budget**: max `WATCHDOG_RESTART_BUDGET_PER_HOUR` restarts in any rolling
  1h window. On exhaustion, restarts skip and audit log records the reason.
- **Circuit breaker**: when tripped, the watchdog will not attempt restart
  on that target for `WATCHDOG_CIRCUIT_COOLOFF_SECONDS`. Manual reset via
  `POST /api/circuit/reset?feed=<name>`.
- **Dry-run**: `WATCHDOG_DRY_RUN=true` logs intentions without acting.
- **Master switch**: `WATCHDOG_ENABLED=false` disables every action.

## Privileges

The container does **not** mount docker.sock. It speaks to
`docker-socket-proxy` over `tcp://socket-proxy:2375`. socket-proxy's
allowlist is `CONTAINERS=1, POST=1, INFO=1, VERSION=1, EVENTS=1` and
nothing else. EXEC, BUILD, IMAGES, NETWORKS, VOLUMES are all denied.

The `docker_client.py` module exposes only `restart()` and a read-only
`list_btc_containers()` — even within the granted permissions we use a
narrow API.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET    | `/healthz`              | liveness |
| GET    | `/metrics`              | Prometheus scrape |
| GET    | `/api/audit?since=<unix_ts>` | audit ring (last 500 actions) |
| GET    | `/api/circuit/list`     | open circuits with TTLs |
| POST   | `/api/circuit/reset?feed=<name>` | manually close a circuit |

All actions are also emitted to stdout as JSON with `event=audit.action`,
indexed by Promtail and queryable in Loki.

## Adding a new policy

1. Implement decide_*() in `policies.py`. Pure function: input snapshot,
   output `list[Action]`.
2. Call it from `_tick()` in `app.py`.
3. Make sure the target is in `RESTART_ALLOWLIST` (or it'll be skipped).
4. Add a section to `RUNBOOK.md` with the same name as the policy.
