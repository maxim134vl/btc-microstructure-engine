"""HTTP server: /healthz /metrics /api/audit /api/circuit/*."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import Config
from .registry import Metrics
from .state import CircuitBreaker, RestartBudget

# Bounded audit ring — survives in-process restarts only.
AUDIT_RING_SIZE = 500


class AuditLog:
    def __init__(self) -> None:
        self._ring: deque[dict[str, Any]] = deque(maxlen=AUDIT_RING_SIZE)

    def add(self, entry: dict[str, Any]) -> None:
        entry["ts"] = time.time()
        self._ring.append(entry)

    def since(self, ts: float) -> list[dict[str, Any]]:
        return [e for e in self._ring if e["ts"] >= ts]

    def all(self) -> list[dict[str, Any]]:
        return list(self._ring)


def make_app(
    cfg: Config,
    metrics: Metrics,
    budget: RestartBudget,
    circuits: CircuitBreaker,
    audit: AuditLog,
    state: dict,
) -> web.Application:
    app = web.Application()

    async def healthz(_req: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "enabled": cfg.enabled, "dry_run": cfg.dry_run})

    async def metrics_handler(_req: web.Request) -> web.Response:
        metrics.budget_used.set(budget.used())
        last_ts = state.get("last_poll_ts")
        metrics.last_poll_age.set(time.time() - last_ts if last_ts else 0)
        return web.Response(body=generate_latest(metrics.registry),
                            headers={"Content-Type": CONTENT_TYPE_LATEST})

    async def audit_handler(req: web.Request) -> web.Response:
        since_param = req.query.get("since")
        if since_param:
            try:
                since = float(since_param)
            except ValueError:
                return web.json_response({"error": "bad since"}, status=400)
            return web.json_response({"audit": audit.since(since)})
        return web.json_response({"audit": audit.all()})

    async def circuit_list(_req: web.Request) -> web.Response:
        return web.json_response({"open": circuits.all_open()})

    async def circuit_reset(req: web.Request) -> web.Response:
        feed = req.query.get("feed")
        if not feed:
            return web.json_response({"error": "missing ?feed"}, status=400)
        reset = circuits.reset(feed)
        audit.add({"event": "audit.circuit.reset", "target": feed, "actor": "api"})
        return web.json_response({"reset": reset, "feed": feed})

    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/api/audit", audit_handler)
    app.router.add_get("/api/circuit/list", circuit_list)
    app.router.add_post("/api/circuit/reset", circuit_reset)
    return app
