"""
HTTP server. Routes:

  GET /api/alerts/active     currently firing alerts (Redis state)
  GET /api/alerts/history    today's resolved/expired alerts (Redis ZSET)
  GET /metrics               Prometheus scrape (self-metrics only)
  GET /healthz               liveness
  GET /readyz                readiness (200 once Redis reachable)
"""

from __future__ import annotations

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import Config
from .registry import Metrics
from .state import AlertState


def make_app(cfg: Config, metrics: Metrics, state: AlertState, log) -> web.Application:
    app = web.Application()
    app["cfg"] = cfg
    app["metrics"] = metrics
    app["state"] = state
    app["log"] = log

    async def alerts_active(_req: web.Request) -> web.Response:
        try:
            items = await state.list_active()
        except Exception:
            metrics.redis_errors.labels("list_active").inc()
            return web.json_response({"alerts": [], "stale": True}, status=503)
        # newest first
        items.sort(key=lambda a: a.get("startsAt") or "", reverse=True)
        return web.json_response({"alerts": items, "count": len(items)})

    async def healthz(_req: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def readyz(_req: web.Request) -> web.Response:
        ok = await state.ping()
        return web.json_response(
            {"status": "ready" if ok else "redis_unreachable"},
            status=200 if ok else 503,
        )

    async def metrics_handler(_req: web.Request) -> web.Response:
        try:
            metrics.cooldowns_active.set(await state.count_cooldowns())
        except Exception:
            metrics.redis_errors.labels("count_cooldowns").inc()
        body = generate_latest(metrics.registry)
        return web.Response(body=body, headers={"Content-Type": CONTENT_TYPE_LATEST})

    app.router.add_get("/api/alerts/active", alerts_active)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", readyz)
    return app
