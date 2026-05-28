"""BTC-ML Runtime Operations Monitor — FastAPI application."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import API_PREFIX, CORS_ORIGINS
from app.services.domain_builders import build_live_snapshot
from app.services.visual_cognition_service import get_visual_cognition_events, get_visual_cognition_snapshot
from app.services.validation_service import (
    build_evolution_snapshot,
    build_validation_snapshot,
    compare_stage1_stage2,
    export_validation_package,
    generate_visual_replay,
    get_conformance_health,
    get_evolution_report,
    get_validation_report,
    run_conformance_validation,
    run_evolution_cycle,
    run_integrated_validation_benchmark,
    run_stage2_validation_benchmark,
    run_validation_benchmark,
)
from app.websocket.hub import hub

REQUIRED_ROUTES = (
    f"{API_PREFIX}/ops/snapshot",
    f"{API_PREFIX}/debug/snapshot",
    f"{API_PREFIX}/validation/snapshot",
    f"{API_PREFIX}/snapshot",
    f"{API_PREFIX}/routes",
    "/health",
    "/ws/live",
)


def log_registered_routes(app: FastAPI) -> None:
    """Print route inventory at startup."""

    print()
    print("REGISTERED API ROUTES")
    print("=" * 40)

    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        paths.add(path)
        methods = getattr(route, "methods", None)
        if methods:
            print(f"  {sorted(methods)} {path}")
        else:
            print(f"  WS      {path}")

    print()
    for required in REQUIRED_ROUTES:
        status = "OK" if required in paths else "MISSING"
        print(f"  [{status}] {required}")

    missing = [route for route in REQUIRED_ROUTES if route not in paths]
    if missing:
        print()
        print("WARNING: required routes missing:", ", ".join(missing))
    print("=" * 40)
    print()
    sys.stdout.flush()


def _register_api_routes(app: FastAPI) -> None:
    """Register operational REST routes on the app (explicit wiring)."""

    @app.get(f"{API_PREFIX}/ops/snapshot", tags=["ops"])
    async def ops_snapshot():
        return await build_ops_snapshot()

    @app.get(f"{API_PREFIX}/debug/snapshot", tags=["debug"])
    async def debug_snapshot():
        return await build_live_snapshot()

    @app.get(f"{API_PREFIX}/snapshot", tags=["ops"])
    async def snapshot_alias():
        return await build_ops_snapshot()

    @app.get(f"{API_PREFIX}/routes", tags=["ops"])
    async def route_inventory():
        routes = []
        for route in app.routes:
            path = getattr(route, "path", None)
            if not path:
                continue
            methods = sorted(getattr(route, "methods", []) or [])
            routes.append({"path": path, "methods": methods, "websocket": not bool(methods)})
        return {"routes": routes}

    @app.get(f"{API_PREFIX}/validation/snapshot", tags=["validation"])
    async def validation_snapshot():
        return await build_validation_snapshot()

    @app.post(f"{API_PREFIX}/validation/run", tags=["validation"])
    async def validation_run(lookback_days: int = 7, forward_horizon: int = 7):
        return await run_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.get(f"{API_PREFIX}/validation/report", tags=["validation"])
    async def validation_report(stage: str = "stage1"):
        return await get_validation_report(stage=stage)

    @app.post(f"{API_PREFIX}/validation/stage2/run", tags=["validation"])
    async def validation_stage2_run(lookback_days: int = 7, forward_horizon: int = 11):
        return await run_stage2_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.post(f"{API_PREFIX}/validation/integrated/run", tags=["validation"])
    async def validation_integrated_run(lookback_days: int = 7, forward_horizon: int = 11):
        return await run_integrated_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.post(f"{API_PREFIX}/validation/conformance/run", tags=["validation"])
    async def validation_conformance_run(lookback_days: int = 7, layer: str | None = None):
        layers = [layer] if layer else None
        return await run_conformance_validation(lookback_days=lookback_days, layers=layers)

    @app.get(f"{API_PREFIX}/validation/conformance/health", tags=["validation"])
    async def validation_conformance_health():
        return await get_conformance_health()

    @app.post(f"{API_PREFIX}/validation/visuals", tags=["validation"])
    async def validation_visuals(stage: str = "stage1", lookback_days: int = 7, forward_horizon: int = 7):
        return await generate_visual_replay(
            stage=stage,
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.get(f"{API_PREFIX}/validation/export", tags=["validation"])
    async def validation_export(stage: str = "stage1"):
        return await export_validation_package(stage=stage)

    @app.get(f"{API_PREFIX}/validation/compare", tags=["validation"])
    async def validation_compare():
        return await compare_stage1_stage2()

    @app.get(f"{API_PREFIX}/validation/evolution/snapshot", tags=["validation"])
    async def validation_evolution_snapshot():
        return await build_evolution_snapshot()

    @app.post(f"{API_PREFIX}/validation/evolution/run", tags=["validation"])
    async def validation_evolution_run(full_cycle: bool = False):
        return await run_evolution_cycle(full_cycle=full_cycle)

    @app.get(f"{API_PREFIX}/validation/evolution/report", tags=["validation"])
    async def validation_evolution_report():
        return await get_evolution_report()

    @app.get(f"{API_PREFIX}/visual-cognition/snapshot", tags=["visual-cognition"])
    async def visual_cognition_snapshot(
        lookback_days: int = 7,
        max_bars: int = 60,
        timestamp: str | None = None,
        event_index: int | None = None,
    ):
        return await get_visual_cognition_snapshot(
            lookback_days=lookback_days,
            max_bars=max_bars,
            timestamp=timestamp,
            event_index=event_index,
        )

    @app.get(f"{API_PREFIX}/visual-cognition/events", tags=["visual-cognition"])
    async def visual_cognition_events(lookback_days: int = 7):
        return await get_visual_cognition_events(lookback_days=lookback_days)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_registered_routes(app)
    await hub.start()
    yield
    await hub.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BTC-ML Runtime Operations Monitor",
        description="Operational infrastructure supervision for canonical runtime",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_api_routes(app)

    @app.get("/health")
    async def health():
        return {"status": "running", "service": "runtime-ops-monitor"}

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket):
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    return app


app = create_app()
