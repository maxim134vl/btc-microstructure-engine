# health-api

Domain health aggregator + WebSocket fanout + UI server.

## Responsibilities

1. Aggregate per-domain health snapshots by querying Prometheus
2. Bridge Redis pubsub (`alerts.live`) to WebSocket clients
3. Push periodic `health.tick` events to WS clients
4. Serve the monitor-ui static bundle

## Endpoints

Documented in [SERVICES.md](../../docs/SERVICES.md#health-api).

## Add a new domain

1. Implement `Aggregator` subclass in `src/btc_health_api/domain/<name>.py`
2. Export from `domain/__init__.py`
3. Append instance in `app.py:_lifespan`

`compute()` returns a `DomainSnapshot(name, status, summary, details)`. The
status enum has `ok`/`degraded`/`down`/`unknown`. The aggregator helper
`self._worst(*statuses)` picks the worst of a list (down > degraded > unknown > ok).

## WebSocket protocol

```
C -> S: {"op":"sub", "topic":"alerts.live"}        // subscribe
C -> S: {"op":"sub", "topic":"health.tick"}        // subscribe
C -> S: {"op":"unsub","topic":"..."}
C -> S: {"op":"ping"}

S -> C: {"event":"subscribed","topic":"..."}
S -> C: {"event":"alert.firing", ...}              // topic alerts.live
S -> C: {"event":"alert.resolved", ...}            // topic alerts.live
S -> C: {"event":"health.tick", "snapshot":{...}}  // topic health.tick
S -> C: {"event":"pong"}
```

Backpressure: each client has a bounded outbound queue. On overflow the
client is force-closed; UI reconnect is cheap.
