# Alerting

## 1. Severity taxonomy

| Severity | Meaning | UI color | Notification |
| --- | --- | --- | --- |
| `critical` | Pipeline down, data flow stopped, or unrecoverable error. Engineer must act now. | red | UI flash + future PagerDuty/Telegram |
| `warning`  | Degraded but not down. Action expected within hours. | amber | UI list + future Slack |
| `info`     | State change worth knowing (e.g. regime flip). | grey | UI list only |

Severity is set by the Prometheus rule's `labels.severity`. No magic.

## 2. Domains

Same 5 as monitoring topology:

| Domain | Sample alerts |
| --- | --- |
| `pipeline`  | `RuntimeStalled`, `RuntimeCrashed`, `PipelineRestartLoop` |
| `dataflow`  | `ParquetStale`, `ParquetSchemaInvalid`, `ParquetEmpty`, `ParquetGrowthCollapse` |
| `feed`      | `FeedDisconnected`, `ReconnectStorm`, `FeedLagHigh` |
| `system`    | `DiskLow`, `MemHigh`, `CpuSaturated`, `ZombieProcess` |
| `research`  | `FeatureNaNExplosion`, `FeatureInfDetected`, `RegimeCollapse`, `NormalizationDrift` |

Each Prometheus rule MUST carry `labels: {severity, domain}` and `annotations: {summary, description, runbook}`.

## 3. Routing

Defined in `infra/alertmanager/alertmanager.yml`:

```
route:
  receiver: alert-engine
  group_by:  [alertname, severity]
  group_wait: 10s
  group_interval: 30s
  repeat_interval: 1h
  routes:
    - matchers: [severity="critical"]   receiver: alert-engine-critical
    - matchers: [severity="warning"]    receiver: alert-engine-warning
    - matchers: [severity="info"]       receiver: alert-engine-info
```

All four receivers point at `alert-engine`'s `:9102/webhook` (route info is
passed in the URL; the engine applies finer per-severity logic).

## 4. Dedup + cooldown logic (alert-engine)

For each incoming alert, fingerprint = `sha1(alertname + sorted_labels)`.

```
on receive:
  if redis.GET("alert:cooldown:<fp>") exists:
      drop, INC btc_alerts_deduped_total
      return
  redis.SETEX("alert:active:<fp>", ttl=cooldown + 60s, JSON)
  redis.SETEX("alert:cooldown:<fp>", ttl=cooldown_for(severity))
  publish("alerts.live", JSON)
  INC btc_alerts_emitted_total{severity, domain}
```

Per-severity defaults (`ALERT_ENGINE_COOLDOWN_DEFAULT_SECONDS`):
- `critical`: 60s
- `warning`: 300s
- `info`: 900s

Per-alert overrides live in `alert-engine/src/policies.py`.

## 5. Escalation (roadmap)

v0.4 will add:
- `critical` not acked within 5 min → escalate to PagerDuty
- Repeated criticals → page secondary on-call
- Auto-silence during planned maintenance window (via API)

MVP: UI-only.

## 6. Silences

Alertmanager silence API is reachable at `/alertmanager/api/v2/silences` through
Traefik. UI link in monitor-ui's alert-center opens the Alertmanager silence
form pre-filled with the alert's labels.

## 7. Alert authoring contract

Every new alert in `infra/prometheus/rules/*.yml` MUST include:

```yaml
- alert: SomeDescriptiveName
  expr: <PromQL>
  for: 30s                                   # avoid flapping
  labels:
    severity: critical | warning | info
    domain: pipeline | dataflow | feed | system | research
  annotations:
    summary: "one-line, what is wrong"
    description: "what is happening, what is impacted, when"
    runbook: "docs/RUNBOOK.md#<anchor>"
```

CI lint will fail PRs that omit any of these.

## 8. Test fires

To verify the path end-to-end:

```bash
make alert-test                                     # fires a synthetic alert
# Equivalent to:
curl -X POST http://localhost:9093/api/v2/alerts -d '[{
  "labels": {"alertname":"SyntheticTest","severity":"info","domain":"system"},
  "annotations": {"summary":"smoke test"},
  "startsAt":"'$(date -u +%FT%TZ)'"
}]'
```

Expected: appears in monitor-ui `Alerts` panel within 30s.
