# BTC-ML Runtime Operations Monitor

Production **infrastructure supervision** dashboard for the canonical runtime.

Answers only:
- Is the machine alive?
- What is dead, stale, disconnected, timing out, failing, or degraded?

**Not** a behavioral cognition terminal, ontology analyzer, or probabilistic research UI.

## Quick start

```bash
# API
cd dashboard/backend
PYTHONPATH=".:../.." ../../venv/bin/python3 run_api.py

# UI
cd dashboard/frontend
npm install && npm run dev
```

Open http://localhost:5173

## Primary panels (default UI)

| Panel | Purpose |
|-------|---------|
| Engine Status | HEALTHY / WAITING / FAILED / TIMEOUT / STALLED |
| Parquet Status | LIVE / STALE / MISSING (grouped) |
| Collector Status | Binance feed, multi-exchange, orderbook, OI |
| Pipeline Status | Cycle, failures, timeouts, heartbeat |
| Runtime Health | HEALTHY / DEGRADED / CRITICAL **with reasons** |
| Operational Alerts | Infrastructure alerts only |

## Top ribbon

`RUNTIME · FEED · PIPELINE · COLLECTORS · PARQUET · ALERTS · HEALTH`

No ontology, cognition, contradictions, or entropy in default view.

## Debug mode

Open `#debug` for legacy cognition/ontology telemetry JSON (`GET /api/v1/debug/snapshot`).

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/ops/snapshot` | Operational monitor snapshot |
| `GET /api/v1/snapshot` | Alias for ops snapshot |
| `GET /api/v1/debug/snapshot` | Full cognition telemetry (debug only) |
| `WS /ws/live` | Live ops snapshot stream |

## Reference

Authoritative architecture: `docs/ARCHITECTURE_REFERENCE.md`

Runtime topology: `docs/FINAL_RUNTIME_TOPOLOGY.md`
