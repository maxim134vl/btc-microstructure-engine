"""Behavioral cognition control center — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import API_PREFIX, CORS_ORIGINS
from app.routers.domains import router as domains_router
from app.websocket.hub import hub


@asynccontextmanager
async def lifespan(_: FastAPI):
    await hub.start()
    yield
    await hub.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BTC-ML Cognition Control Center",
        description="Operational observability for canonical behavioral runtime",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(domains_router, prefix=API_PREFIX)

    @app.get("/health")
    async def health():
        return {"status": "running", "service": "cognition-control-center"}

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
