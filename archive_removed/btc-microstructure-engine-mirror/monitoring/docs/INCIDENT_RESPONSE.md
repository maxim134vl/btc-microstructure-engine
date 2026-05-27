# Incident Response

## Triage matrix

| Symptom in monitor-ui | First check | Likely cause |
| --- | --- | --- |
| `SYSTEM` pill red, others green     | `make logs SVC=watchdog` and `docker ps` | Host kernel / docker daemon |
| `FEED` pill red, others green       | exchange status page; `make logs SVC=binance-feed` | Upstream WS dead, geo block, API rotation |
| `DATA` red, `FEED` green            | `ls -la /var/lib/docker/volumes/btc_engine_data/_data/*.parquet` | Disk full, FS errors, write contention |
| `RUNTIME` red, everything else fine | `make logs SVC=pipeline --tail=500` | Pipeline crash loop, regression in engine code |
| `FEATURES` red                      | metrics-exporter logs; query Prom for `btc_feature_nan_ratio` | Schema drift, NaN explosion, normalization breakage |
| `ALERTS` flood (>20/min)            | Alertmanager UI silences | Cascading alert dependencies — silence root cause first |

## Severity-1 (Critical) playbook

System fully down OR data flow halted > 5 min.

1. **Stabilize**
   - Open monitor-ui — read top-bar pills, confirm scope
   - If host issue → `ssh` to host; `docker ps`, `df -h`, `free -m`, `uptime`
   - If service issue → identify failing container

2. **Contain**
   - Silence noisy downstream alerts (Alertmanager → Silences → match `domain=<X>`)
   - Do **not** restart blindly: watchdog has a 10/hr restart budget — if you exceed it, the budget locks out

3. **Diagnose**
   - `make logs SVC=<name> --tail=2000` — look for first ERROR after last successful state
   - In Grafana → "Engine drill-down" dashboard for last 30 min metrics
   - In Loki → query `{service="<name>", level=~"ERROR|CRITICAL"}`

4. **Mitigate**
   - Container crash loop: `make restart-svc SVC=<name>`
   - Disk full: free `/data` (rotate old parquets per RUNBOOK §disk-cleanup)
   - OOM: bump memory limit in `docker-compose.prod.yml`, redeploy

5. **Postmortem**
   - File a Markdown postmortem in `docs/postmortems/YYYY-MM-DD-<slug>.md`
   - Add the alert/runbook gap to `docs/RUNBOOK.md` so the next person doesn't redo this

## Severity-2 (Warning) playbook

Degradation, not outage. Single component partially impaired.

1. Acknowledge the alert in monitor-ui (or set Alertmanager silence with TTL ≤ 2h)
2. Investigate in business hours
3. If unresolved by TTL, alert re-fires → re-evaluate

## Security incidents

If the alert is in the `audit.*` log stream and the actor is **not** `watchdog`:

1. **Freeze** — `make down` to stop everything
2. **Snapshot** — image the host filesystem; preserve Loki + Prom data
3. **Notify** — do not push fixes through normal CI
4. **Investigate** off-host using snapshots
5. Resume only after rotating all secrets in `.env`

See [SECURITY.md §7](SECURITY.md#7-incident-reporting) for the formal flow.

## Restart budget exhausted

If watchdog says it has skipped restarts:
- monitor-ui shows `WATCHDOG: budget exhausted (10/10 hr)` banner
- Wait for the rolling 1h window to pass (watchdog `/api/audit` shows next slot)
- OR set `WATCHDOG_RESTART_BUDGET_PER_HOUR=0` (kills auto-restart entirely), do manual restarts, and reset by `make restart-svc SVC=watchdog`

## Loss of observability

If Prometheus is down:
- Engine is unaffected. Confirm via direct `docker ps` and `ls -la /data/*.parquet` (mtime should still advance).
- Restart Prom: `make restart-svc SVC=prometheus`
- Last 15 days of metrics may be lost if data dir is corrupted; engine remains functional.

If Loki is down:
- Use `docker logs <container>` directly until Loki recovers.

## Contacts

Define in `docs/CONTACTS.md` (not version-controlled; copy from secrets store).
