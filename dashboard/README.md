# Cognition Control Center

Production-grade **operator cockpit** for supervising the live BTC behavioral runtime platform.

This is **not** a trading terminal. It exposes existing runtime parquet surfaces with **operator-grade information hierarchy** — primary supervision first, forensic drill-down collapsed by default.

## Operator layout

| Zone | Content |
|------|---------|
| **Top ribbon** | Runtime, Feed, Regime, D1, Ontology, Contradictions, Drift, Latency, Health, WS, Pipeline |
| **Left** | Current Behavioral State narrative · D1 structural anchor · Active regime |
| **Center** | Auction state · Ontology activity · MTF alignment (D1 → M15) |
| **Right** | Runtime health · Contradiction state · Prioritized alerts |
| **Bottom (collapsed)** | Advanced diagnostics · Forensic/audit · Debug/topology |

## 5-second questions answered

1. Runtime healthy? → Ribbon `RUNTIME` + narrative
2. Cognition stable? → Narrative `Cognition` + `Contradictions`
3. Current regime? → Ribbon `REGIME` + left panel
4. D1 structural bias? → Ribbon `D1` + dominant D1 panel
5. Contradictions escalating? → Ribbon + right panel
6. Ontology normal? → Ribbon `ONTOLOGY` + center feed
7. System degrading? → Alerts + `DRIFT` / `HEALTH`
8. Operationally safe? → Composite ribbon severity + alert count

## Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, asyncio, WebSocket, parquet readers |
| Frontend | React, TypeScript, Tailwind, Zustand |
| Data | Canonical `data/` parquet via `storage/path_registry.py` |

## Quick start

```bash
# Terminal 1 — API (from repo root)
cd dashboard/backend
PYTHONPATH=".:../.." ../../venv/bin/python3 run_api.py

# Terminal 2 — UI
cd dashboard/frontend
npm install
npm run dev
```

Open http://localhost:5173

Or use the launcher:

```bash
bash dashboard/scripts/start_dashboard.sh
```

## API

| Endpoint | Domain |
|----------|--------|
| `GET /health` | Service health |
| `GET /api/v1/snapshot` | Full live snapshot |
| `GET /api/v1/runtime/operations` | Runtime ops panel |
| `GET /api/v1/ontology` | Behavioral ontology |
| `GET /api/v1/cognition/probabilistic` | Probabilistic cognition |
| `GET /api/v1/state-transitions` | State transitions |
| `GET /api/v1/mtf/cognition` | Multi-timeframe (M15–D1) |
| `GET /api/v1/reinforcement` | Reinforcement & contradictions |
| `GET /api/v1/regime` | Regime monitoring |
| `GET /api/v1/health/runtime` | Parquet integrity |
| `GET /api/v1/replay` | Replay & audit exports |
| `GET /api/v1/topology` | Pipeline topology |
| `WS /ws/live` | Live snapshot stream (~2s) |

## Domains (10 panels)

1. Runtime Operations
2. Behavioral Ontology
3. Probabilistic Cognition
4. State Transitions
5. Multi-Timeframe Cognition (D1 via read-only observability layer)
6. Reinforcement & Contradictions
7. Regime Monitoring
8. Runtime Health
9. Replay & Audit
10. System Topology

## Architecture constraints

- **Does not** modify ontology, cognition logic, or runtime behavior
- **Reads** canonical parquet and existing diagnostic exports only
- D1 is computed read-only from `candle_structure_memory.parquet` using the same aggregation semantics as runtime builders (dashboard-local mirror in `mtf_observability.py` to avoid importing modules with side effects)

## Legacy

`monitoring_api_v1.py` and `runtime-dashboard/` remain as earlier minimal prototypes. Use `dashboard/` for the control center.

## Reference

Authoritative architecture: `docs/ARCHITECTURE_REFERENCE.md`

Runtime topology: `docs/FINAL_RUNTIME_TOPOLOGY.md`
