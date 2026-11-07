"""BTC-ML Runtime Operations Monitor — FastAPI application."""

from __future__ import annotations

import sys
import asyncio
from urllib.parse import urlencode
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.transport_config import API_PREFIX, CORS_ORIGINS
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
    """Only ready-message delivery. Job execution requires an owner interface."""
    import app.services.published_transport as publications

    def endpoint_for(section, method):
        async def deliver(request: Request):
            if method == "post":
                raise HTTPException(503, detail={"status":"OWNER_EXECUTION_INTERFACE_NOT_AVAILABLE", "route":request.url.path})
            if section is None:
                return await publications.build_published_snapshot()
            request_key=urlencode(sorted(request.query_params.multi_items()))
            payload,metadata=publications.transport.read(section,request_key=request_key)
            if metadata['status']!='AVAILABLE':
                raise HTTPException(503,detail=metadata)
            return payload
        return deliver

    @app.get(f"{API_PREFIX}/release", tags=["ops"])
    async def release_info():
        from app.services.runtime_observation import release_manifest
        return release_manifest()

    @app.get(f"{API_PREFIX}/market-context/chart", tags=["ops"])
    async def market_context_chart():
        from app.services.chart_presentation import read_chart
        return await asyncio.to_thread(read_chart)

    @app.get(f"{API_PREFIX}/routes",tags=["ops"])
    async def route_inventory():
        return {"routes":[{"path":r.path,"methods":sorted(getattr(r,'methods',[]) or []),
                            "websocket":not bool(getattr(r,'methods',[]))}
                           for r in app.routes if getattr(r,'path',None)]}

    app.add_api_route('/api/v1/ops/snapshot', endpoint_for(None, 'get'), methods=['GET'])
    app.add_api_route('/api/v1/debug/snapshot', endpoint_for('debug_snapshot', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/snapshot', endpoint_for(None, 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/snapshot', endpoint_for('validation_snapshot', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/run', endpoint_for('validation_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/report', endpoint_for('validation_report', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/stage2/run', endpoint_for('validation_stage2_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/stage2_5/run', endpoint_for('validation_stage2_5_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/stage2_5/compare', endpoint_for('validation_stage2_5_compare', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/stage2_5/calibration', endpoint_for('validation_stage2_5_calibration', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/stage2_5/calibration/run', endpoint_for('validation_stage2_5_calibration_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/integrated/run', endpoint_for('validation_integrated_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/conformance/run', endpoint_for('validation_conformance_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/conformance/health', endpoint_for('validation_conformance_health', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/visuals', endpoint_for('validation_visuals', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/export', endpoint_for('validation_export', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/compare', endpoint_for('validation_compare', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/evolution/snapshot', endpoint_for('validation_evolution_snapshot', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/validation/evolution/run', endpoint_for('validation_evolution_run', 'post'), methods=['POST'])
    app.add_api_route('/api/v1/validation/evolution/report', endpoint_for('validation_evolution_report', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/visual-cognition/snapshot', endpoint_for('visual_cognition_snapshot', 'get'), methods=['GET'])
    app.add_api_route('/api/v1/visual-cognition/events', endpoint_for('visual_cognition_events', 'get'), methods=['GET'])


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_registered_routes(app)
    await hub.start()
    try:
        yield
    finally:
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
        release = {"version": "2026.09.22", "channel": "release", "app": "btc-ml-paper"}
        try:
            from btc_ml.release_identity import load_release_identity

            loaded = load_release_identity()
            if isinstance(loaded, dict) and loaded.get("version"):
                release = loaded
        except Exception:
            pass
        return {"status": "running", "service": "runtime-ops-monitor", "release": release}

    _register_api_routes(app)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket):
        try:
            await hub.connect(websocket)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(websocket)

    return app


app = create_app()
