# alert-engine

Webhook receiver that sits between Alertmanager and the rest of the stack.

## What it does

For each alert coming in from Alertmanager:

1. Fingerprint = sha1(alertname + sorted labels)
2. If fingerprint is in cooldown → drop (counted in `btc_alerts_deduped_total`)
3. Otherwise: store in Redis with TTL, publish on the `alerts.live` pubsub channel
4. health-api's WS bridge picks it up and pushes to monitor-ui

It does **not** notify out-of-band (Slack/PagerDuty/Telegram) — those routes
will be wired in v0.4 by adding additional receivers to `alertmanager.yml`.

## Why not just use Alertmanager?

AM handles dedup + grouping at routing time. We need a *post-routing* layer that
keeps state across restarts (Redis) and exposes a clean fanout point for the
UI WebSocket. The split keeps AM stateless and allows us to add custom logic
(cooldown overrides per alertname, audit log, etc.) without forking AM.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST   | `/webhook`              | AM v4 webhook target |
| GET    | `/api/alerts/active`    | list active alerts (used by health-api on cold start) |
| GET    | `/metrics`              | Prometheus scrape |
| GET    | `/healthz`              | liveness |
| GET    | `/readyz`               | 200 only if Redis is reachable |

## Configure

See `.env.example`. Key knobs:

- `ALERT_ENGINE_COOLDOWN_DEFAULT_SECONDS` (default 300)
- per-severity defaults live in `config.py:DEFAULT_COOLDOWNS`
- per-alertname overrides live in `policies.py:COOLDOWN_OVERRIDES`

## Test fire

```bash
make alert-test                              # synthetic alert
# or directly:
curl -X POST http://localhost:9102/webhook?severity=info \
  -H 'Content-Type: application/json' \
  -d '{"version":"4","alerts":[{"status":"firing","labels":{"alertname":"Smoke","severity":"info","domain":"system"},"annotations":{"summary":"x"},"startsAt":"2026-01-01T00:00:00Z"}]}'
```
