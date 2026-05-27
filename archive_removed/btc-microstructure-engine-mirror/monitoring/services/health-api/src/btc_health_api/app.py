"""FastAPI app factory + lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from .aggregator import Aggregator
from .clients import (
    AlertsClient,
    CAdvisorClient,
    DockerClient,
    MetricsClient,
    NodeExporterClient,
    WatchdogClient,
)
from .config import Config
from .logging import configure_logging


def _self_metrics() -> tuple[CollectorRegistry, dict]:
    r = CollectorRegistry(auto_describe=True)
    return r, {
        "requests": Counter("btc_health_api_requests_total",
                            "HTTP requests by path/status", ["path", "status"], registry=r),
        "errors": Counter("btc_health_api_upstream_errors_total",
                          "Upstream client errors by name", ["upstream"], registry=r),
        "aggregate_duration": Gauge("btc_health_api_aggregate_duration_seconds",
                                    "Last fetch_all wall-clock seconds", registry=r),
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cfg: Config = app.state.cfg
    log = app.state.log

    metrics = MetricsClient(cfg.metrics_url, cfg.upstream_timeout_seconds)
    alerts = AlertsClient(cfg.alert_engine_url, cfg.upstream_timeout_seconds)
    watchdog = WatchdogClient(cfg.watchdog_url, cfg.upstream_timeout_seconds)
    cadvisor = CAdvisorClient(cfg.cadvisor_url, cfg.upstream_timeout_seconds)
    node = NodeExporterClient(cfg.node_exporter_url, cfg.upstream_timeout_seconds)
    docker = DockerClient(cfg.docker_socket, cfg.upstream_timeout_seconds)

    aggregator = Aggregator(metrics, alerts, watchdog, cadvisor, node, docker)

    app.state.metrics_client = metrics
    app.state.alerts_client = alerts
    app.state.watchdog_client = watchdog
    app.state.cadvisor_client = cadvisor
    app.state.node_client = node
    app.state.docker_client = docker
    app.state.aggregator = aggregator

    log.info("startup.complete")
    try:
        yield
    finally:
        log.info("shutdown.begin")
        for c in (metrics, alerts, watchdog, cadvisor, node, docker):
            try:
                await c.close()
            except Exception:
                pass
        log.info("shutdown.complete")


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    cfg.validate()
    log = configure_logging(cfg)

    reg, m_self = _self_metrics()

    app = FastAPI(
        title="btc-health-api",
        version=cfg.service_version,
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.cfg = cfg
    app.state.log = log
    app.state.self_metrics = m_self

    templates = Jinja2Templates(directory=str(cfg.template_dir))
    templates.env.filters["fmt_bytes"] = _fmt_bytes
    templates.env.filters["fmt_pct"] = _fmt_pct
    templates.env.filters["fmt_age"] = _fmt_age
    templates.env.filters["fmt_n"] = _fmt_n
    templates.env.globals["zip"] = zip   # jinja has no built-in zip; used by compare.html
    app.state.templates = templates

    if cfg.static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(cfg.static_dir)), name="static")

    # ---------- HEALTH PROBES ----------
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        ok = await app.state.metrics_client.healthy()
        return JSONResponse(
            {"status": "ready" if ok else "metrics_exporter_unreachable"},
            status_code=200 if ok else 503,
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(reg).decode("utf-8"),
                                 media_type=CONTENT_TYPE_LATEST)

    # ---------- VIEW: BASE CONTEXT ----------
    async def _base_ctx(request: Request) -> dict:
        return {
            "request": request,
            "now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "refresh_s": cfg.refresh_interval_seconds,
            "service_version": cfg.service_version,
        }

    # ---------- PAGES ----------
    @app.get("/", response_class=HTMLResponse)
    async def page_dashboard(request: Request):
        data = await app.state.aggregator.fetch_all()
        view = app.state.aggregator.dashboard_view(data)
        ctx = await _base_ctx(request)
        ctx.update({"page": "dashboard", "view": view, "data": data})
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    @app.get("/services", response_class=HTMLResponse)
    async def page_services(request: Request):
        data = await app.state.aggregator.fetch_all()
        ctx = await _base_ctx(request)
        ctx.update({"page": "services", "data": data})
        return templates.TemplateResponse(request, "services.html", ctx)

    @app.get("/parquets", response_class=HTMLResponse)
    async def page_parquets(request: Request):
        data = await app.state.aggregator.fetch_all()
        ctx = await _base_ctx(request)
        ctx.update({"page": "parquets", "data": data})
        return templates.TemplateResponse(request, "parquets.html", ctx)

    @app.get("/alerts", response_class=HTMLResponse)
    async def page_alerts(request: Request):
        data = await app.state.aggregator.fetch_all()
        circuits = await app.state.watchdog_client.circuit_list()
        audit = await app.state.watchdog_client.audit()
        ctx = await _base_ctx(request)
        ctx.update({"page": "alerts", "data": data, "circuits": circuits, "audit": audit[-100:]})
        return templates.TemplateResponse(request, "alerts.html", ctx)

    @app.get("/system", response_class=HTMLResponse)
    async def page_system(request: Request):
        data = await app.state.aggregator.fetch_all()
        ctx = await _base_ctx(request)
        ctx.update({"page": "system", "data": data})
        return templates.TemplateResponse(request, "system.html", ctx)

    @app.get("/logs", response_class=HTMLResponse)
    async def page_logs(request: Request, container: str | None = None):
        data = await app.state.aggregator.fetch_all()
        log_text = ""
        if container:
            log_text = await app.state.docker_client.logs_tail(container, lines=200)
        ctx = await _base_ctx(request)
        ctx.update({"page": "logs", "data": data, "container": container, "log_text": log_text})
        return templates.TemplateResponse(request, "logs.html", ctx)

    @app.get("/state", response_class=HTMLResponse)
    async def page_state(request: Request, file: str | None = None, rows: int = 100):
        data = await app.state.aggregator.fetch_all()
        preview = None
        if file:
            preview = await app.state.metrics_client.preview(file, rows=rows)
        history = await app.state.metrics_client.history()
        ctx = await _base_ctx(request)
        ctx.update({"page": "state", "data": data, "file": file,
                    "preview": preview, "rows": rows, "history": history})
        return templates.TemplateResponse(request, "state.html", ctx)

    @app.get("/compare", response_class=HTMLResponse)
    async def page_compare(request: Request,
                           a: str | None = None,
                           b: str | None = None,
                           rows: int = 50):
        data = await app.state.aggregator.fetch_all()
        history = await app.state.metrics_client.history()
        preview_a = await app.state.metrics_client.preview(a, rows=rows) if a else None
        preview_b = await app.state.metrics_client.preview(b, rows=rows) if b else None
        ctx = await _base_ctx(request)
        ctx.update({"page": "compare", "data": data, "history": history,
                    "a": a, "b": b, "rows": rows,
                    "preview_a": preview_a, "preview_b": preview_b})
        return templates.TemplateResponse(request, "compare.html", ctx)

    # ---------- HTMX PARTIALS ----------
    @app.get("/partials/stat-cards", response_class=HTMLResponse)
    async def partial_stat_cards(request: Request):
        data = await app.state.aggregator.fetch_all()
        view = app.state.aggregator.dashboard_view(data)
        return templates.TemplateResponse(request, "partials/stat_cards.html",
                                          {"request": request, "view": view})

    @app.get("/partials/services-table", response_class=HTMLResponse)
    async def partial_services_table(request: Request):
        data = await app.state.aggregator.fetch_all()
        return templates.TemplateResponse(request, "partials/services_table.html",
                                          {"request": request, "data": data})

    @app.get("/partials/parquets-table", response_class=HTMLResponse)
    async def partial_parquets_table(request: Request):
        data = await app.state.aggregator.fetch_all()
        return templates.TemplateResponse(request, "partials/parquets_table.html",
                                          {"request": request, "data": data})

    @app.get("/partials/alerts-table", response_class=HTMLResponse)
    async def partial_alerts_table(request: Request):
        data = await app.state.aggregator.fetch_all()
        return templates.TemplateResponse(request, "partials/alerts_table.html",
                                          {"request": request, "data": data})

    @app.get("/partials/system-panel", response_class=HTMLResponse)
    async def partial_system_panel(request: Request):
        data = await app.state.aggregator.fetch_all()
        return templates.TemplateResponse(request, "partials/system_panel.html",
                                          {"request": request, "data": data})

    @app.get("/partials/domains-overview", response_class=HTMLResponse)
    async def partial_domains_overview(request: Request):
        data = await app.state.aggregator.fetch_all()
        view = app.state.aggregator.dashboard_view(data)
        return templates.TemplateResponse(request, "partials/domains_overview.html",
                                          {"request": request, "view": view})

    @app.get("/partials/live-chart", response_class=HTMLResponse)
    async def partial_live_chart(request: Request):
        data = await app.state.aggregator.fetch_all()
        return templates.TemplateResponse(request, "partials/live_chart.html",
                                          {"request": request, "data": data})

    @app.get("/partials/logs/{container}", response_class=PlainTextResponse)
    async def partial_logs(container: str, lines: int = Query(default=200, ge=1, le=2000)):
        text = await app.state.docker_client.logs_tail(container, lines=lines)
        return PlainTextResponse(text, media_type="text/plain")

    # ---------- JSON API ----------
    @app.get("/api/health")
    async def api_health():
        data = await app.state.aggregator.fetch_all()
        return app.state.aggregator.dashboard_view(data)

    @app.get("/api/services")
    async def api_services():
        data = await app.state.aggregator.fetch_all()
        return {"containers": data["containers"], "per_container_rt": data["per_container_rt"]}

    @app.get("/api/parquets")
    async def api_parquets():
        snap = await app.state.metrics_client.snapshot() or {}
        return {"parquets": snap.get("parquets", []), "features": snap.get("features", []),
                "regime": snap.get("regime", {}), "runtime": snap.get("runtime", {})}

    @app.get("/api/parquets/history")
    async def api_parquets_history():
        return {"history": await app.state.metrics_client.history()}

    @app.get("/api/parquets/preview/{file:path}")
    async def api_parquet_preview(file: str, rows: int = 100):
        if "/" in file or ".." in file:
            raise HTTPException(400, "invalid file")
        preview = await app.state.metrics_client.preview(file, rows=rows)
        if preview is None:
            raise HTTPException(404, "not found or upstream error")
        return preview

    @app.get("/api/parquets/csv/{file:path}")
    async def api_parquet_csv(file: str, rows: int = 100_000):
        if "/" in file or ".." in file:
            raise HTTPException(400, "invalid file")
        blob = await app.state.metrics_client.preview_csv(file, rows=rows)
        if blob is None:
            raise HTTPException(404, "not found or upstream error")
        out_name = file.rsplit(".parquet", 1)[0] + ".csv"
        return Response(
            content=blob,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
        )

    @app.get("/api/alerts/active")
    async def api_alerts():
        items = await app.state.alerts_client.active()
        return {"alerts": items, "count": len(items)}

    @app.get("/api/system")
    async def api_system():
        return await app.state.node_client.host_stats() or {}

    @app.post("/api/services/{name}/restart")
    async def api_restart(name: str):
        # Only allow names starting with btc_ as a sanity guard
        if not name.startswith("btc_"):
            raise HTTPException(400, "name must start with btc_")
        ok = await app.state.docker_client.restart(name)
        return {"restarted": ok, "name": name}

    @app.get("/api/audit")
    async def api_audit():
        return {"audit": await app.state.watchdog_client.audit()}

    return app


# ---- jinja filters ---------------------------------------------------------
# `jinja2.Undefined` propagates from missing attrs (e.g. dict.foo where foo
# is absent) and explodes when coerced to a number. _coerce returns None for
# both None and Undefined, so callers can render "—" uniformly.
from jinja2 import Undefined as _JUndef


def _coerce(x):
    if x is None or isinstance(x, _JUndef):
        return None
    return x


def _fmt_bytes(n) -> str:
    n = _coerce(n)
    if n is None: return "—"
    try:
        n = float(n)
    except (ValueError, TypeError):
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0: return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"


def _fmt_pct(x) -> str:
    x = _coerce(x)
    if x is None: return "—"
    try:
        return f"{float(x)*100:.1f}%"
    except (ValueError, TypeError):
        return "—"


def _fmt_age(s) -> str:
    s = _coerce(s)
    if s is None: return "—"
    try:
        s = float(s)
    except (ValueError, TypeError):
        return "—"
    if s < 60: return f"{s:.0f}s"
    if s < 3600: return f"{s/60:.1f}m"
    if s < 86400: return f"{s/3600:.1f}h"
    return f"{s/86400:.1f}d"


def _fmt_n(x, prec: int = 0) -> str:
    x = _coerce(x)
    if x is None: return "—"
    try:
        return f"{float(x):,.{prec}f}"
    except (ValueError, TypeError):
        return "—"
