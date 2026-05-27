"""
HTTP server. Exposes:
  GET /metrics                    Prometheus text format (3rd-party scrapers)
  GET /api/snapshot               structured JSON snapshot (health-api + alert-engine)
  GET /api/history/rows           per-file ring buffer of (ts, rows) — for sparklines
  GET /api/preview/{file}?rows=N  columns + last N rows of a given parquet
  GET /healthz, /readyz
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .preview import DEFAULT_ROWS, MAX_CSV_ROWS, preview_csv, preview_parquet
from .registry import Metrics
from .snapshot import build_snapshot


def make_app(metrics: Metrics, state: dict, data_dir: Path) -> web.Application:
    app = web.Application()

    async def metrics_handler(_req: web.Request) -> web.Response:
        body = generate_latest(metrics.registry)
        return web.Response(body=body, headers={"Content-Type": CONTENT_TYPE_LATEST})

    async def snapshot_handler(_req: web.Request) -> web.Response:
        snap = build_snapshot(metrics.registry)
        snap["scan_seq"] = state.get("scans_completed", 0)
        return web.json_response(snap)

    async def history_handler(_req: web.Request) -> web.Response:
        # ring buffers live in state["history"] (filled by parquet_scanner)
        return web.json_response({"history": state.get("history", {})})

    async def preview_handler(req: web.Request) -> web.Response:
        basename = req.match_info["file"]
        try:
            n = int(req.query.get("rows", DEFAULT_ROWS))
        except ValueError:
            return web.json_response({"error": "rows must be int"}, status=400)
        loop = asyncio.get_running_loop()
        try:
            payload = await loop.run_in_executor(None, preview_parquet, data_dir, basename, n)
            return web.json_response(payload)
        except FileNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)

    async def preview_csv_handler(req: web.Request) -> web.StreamResponse:
        basename = req.match_info["file"]
        try:
            n = int(req.query.get("rows", MAX_CSV_ROWS))
        except ValueError:
            return web.json_response({"error": "rows must be int"}, status=400)
        loop = asyncio.get_running_loop()
        try:
            blob = await loop.run_in_executor(None, preview_csv, data_dir, basename, n)
        except FileNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)
        out_name = basename.rsplit(".parquet", 1)[0] + ".csv"
        return web.Response(
            body=blob,
            headers={
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": f'attachment; filename="{out_name}"',
            },
        )

    async def healthz(_req: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def readyz(_req: web.Request) -> web.Response:
        if state.get("scans_completed", 0) > 0:
            return web.json_response({"status": "ready"})
        return web.json_response({"status": "warming_up"}, status=503)

    app.router.add_get("/metrics",                metrics_handler)
    app.router.add_get("/api/snapshot",           snapshot_handler)
    app.router.add_get("/api/history/rows",       history_handler)
    # Order matters: the .csv variant is more specific, register it first.
    app.router.add_get(r"/api/preview/{file:.+}.csv", preview_csv_handler)
    app.router.add_get(r"/api/preview/{file:.+}",     preview_handler)
    app.router.add_get("/healthz",                healthz)
    app.router.add_get("/readyz",                 readyz)
    return app
