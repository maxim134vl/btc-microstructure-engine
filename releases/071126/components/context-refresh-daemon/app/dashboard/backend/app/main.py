"""BTC-ML Runtime Operations Monitor — FastAPI application."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import API_PREFIX, CORS_ORIGINS
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
    """Register operational REST routes on the app (explicit wiring).

    Heavy service imports are deferred to first request so /health can bind
    before pandas/ops_monitor/validation stacks finish loading under low RAM.
    """

    @app.get(f"{API_PREFIX}/ops/snapshot", tags=["ops"])
    async def ops_snapshot():
        from app.services.ops_monitor import build_ops_snapshot

        return await build_ops_snapshot()

    @app.get(f"{API_PREFIX}/debug/snapshot", tags=["debug"])
    async def debug_snapshot():
        from app.services.domain_builders import build_live_snapshot

        return await build_live_snapshot()

    @app.get(f"{API_PREFIX}/snapshot", tags=["ops"])
    async def snapshot_alias():
        from app.services.ops_monitor import build_ops_snapshot

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
        from app.services.validation_service import build_validation_snapshot

        return await build_validation_snapshot()

    @app.post(f"{API_PREFIX}/validation/run", tags=["validation"])
    async def validation_run(lookback_days: int = 7, forward_horizon: int = 7):
        from app.services.validation_service import run_validation_benchmark

        return await run_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.get(f"{API_PREFIX}/validation/report", tags=["validation"])
    async def validation_report(stage: str = "stage1"):
        from app.services.validation_service import get_validation_report

        return await get_validation_report(stage=stage)

    @app.post(f"{API_PREFIX}/validation/stage2/run", tags=["validation"])
    async def validation_stage2_run(lookback_days: int = 7, forward_horizon: int = 11):
        from app.services.validation_service import run_stage2_validation_benchmark

        return await run_stage2_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.post(f"{API_PREFIX}/validation/stage2_5/run", tags=["validation"])
    async def validation_stage2_5_run(
        lookback_days: int | None = None,
        start: str | None = "2026-05-21",
        end: str | None = "2026-05-28 23:59:59",
    ):
        from app.services.validation_service import run_stage2_5_validation_benchmark

        if lookback_days is not None:
            return await run_stage2_5_validation_benchmark(lookback_days=lookback_days)
        return await run_stage2_5_validation_benchmark(start=start, end=end)

    @app.get(f"{API_PREFIX}/validation/stage2_5/compare", tags=["validation"])
    async def validation_stage2_5_compare():
        from app.services.validation_service import compare_stage2_5_vs_outcome_report

        return await compare_stage2_5_vs_outcome_report()

    @app.get(f"{API_PREFIX}/validation/stage2_5/calibration", tags=["validation"])
    async def validation_stage2_5_calibration():
        from app.services.validation_service import get_stage2_5_calibration_snapshot

        return await get_stage2_5_calibration_snapshot()

    @app.post(f"{API_PREFIX}/validation/stage2_5/calibration/run", tags=["validation"])
    async def validation_stage2_5_calibration_run(force: bool = False):
        from app.services.validation_service import run_stage2_5_calibration

        return await run_stage2_5_calibration(force=force)

    @app.post(f"{API_PREFIX}/validation/integrated/run", tags=["validation"])
    async def validation_integrated_run(lookback_days: int = 7, forward_horizon: int = 11):
        from app.services.validation_service import run_integrated_validation_benchmark

        return await run_integrated_validation_benchmark(
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.post(f"{API_PREFIX}/validation/conformance/run", tags=["validation"])
    async def validation_conformance_run(lookback_days: int = 7, layer: str | None = None):
        from app.services.validation_service import run_conformance_validation

        layers = [layer] if layer else None
        return await run_conformance_validation(lookback_days=lookback_days, layers=layers)

    @app.get(f"{API_PREFIX}/validation/conformance/health", tags=["validation"])
    async def validation_conformance_health():
        from app.services.validation_service import get_conformance_health

        return await get_conformance_health()

    @app.post(f"{API_PREFIX}/validation/visuals", tags=["validation"])
    async def validation_visuals(stage: str = "stage1", lookback_days: int = 7, forward_horizon: int = 7):
        from app.services.validation_service import generate_visual_replay

        return await generate_visual_replay(
            stage=stage,
            lookback_days=lookback_days,
            forward_horizon=forward_horizon,
        )

    @app.get(f"{API_PREFIX}/validation/export", tags=["validation"])
    async def validation_export(stage: str = "stage1"):
        from app.services.validation_service import export_validation_package

        return await export_validation_package(stage=stage)

    @app.get(f"{API_PREFIX}/validation/compare", tags=["validation"])
    async def validation_compare():
        from app.services.validation_service import compare_stage1_stage2

        return await compare_stage1_stage2()

    @app.get(f"{API_PREFIX}/validation/evolution/snapshot", tags=["validation"])
    async def validation_evolution_snapshot():
        from app.services.validation_service import build_evolution_snapshot

        return await build_evolution_snapshot()

    @app.post(f"{API_PREFIX}/validation/evolution/run", tags=["validation"])
    async def validation_evolution_run(full_cycle: bool = False):
        from app.services.validation_service import run_evolution_cycle

        return await run_evolution_cycle(full_cycle=full_cycle)

    @app.get(f"{API_PREFIX}/validation/evolution/report", tags=["validation"])
    async def validation_evolution_report():
        from app.services.validation_service import get_evolution_report

        return await get_evolution_report()

    @app.get(f"{API_PREFIX}/visual-cognition/snapshot", tags=["visual-cognition"])
    async def visual_cognition_snapshot(
        lookback_days: int = 7,
        max_bars: int = 60,
        timestamp: str | None = None,
        event_index: int | None = None,
    ):
        from app.services.visual_cognition_service import get_visual_cognition_snapshot

        return await get_visual_cognition_snapshot(
            lookback_days=lookback_days,
            max_bars=max_bars,
            timestamp=timestamp,
            event_index=event_index,
        )

    @app.get(f"{API_PREFIX}/visual-cognition/events", tags=["visual-cognition"])
    async def visual_cognition_events(lookback_days: int = 7):
        from app.services.visual_cognition_service import get_visual_cognition_events

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

    # Bind /health before heavy route registration so cold-start healthchecks
    # can succeed while snapshot/validation stacks stay lazy.
    @app.get("/health")
    async def health():
        return {"status": "running", "service": "runtime-ops-monitor"}

    _register_api_routes(app)

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
