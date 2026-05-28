"""WebSocket broadcast hub for live dashboard updates."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.config import POLL_INTERVAL_S
from app.services.domain_builders import build_live_snapshot


class WebSocketHub:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self._task: asyncio.Task | None = None
        self._latest: dict[str, Any] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)
        if self._latest:
            await websocket.send_text(json.dumps({"type": "snapshot", "data": self._latest}))

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                snapshot = await build_live_snapshot()
                self._latest = snapshot
                if self.connections:
                    payload = json.dumps({"type": "snapshot", "data": snapshot})
                    dead: list[WebSocket] = []
                    for connection in self.connections:
                        try:
                            await connection.send_text(payload)
                        except Exception:
                            dead.append(connection)
                    for connection in dead:
                        self.disconnect(connection)
            except Exception as error:
                error_payload = json.dumps({"type": "error", "message": str(error)})
                for connection in list(self.connections):
                    try:
                        await connection.send_text(error_payload)
                    except Exception:
                        self.disconnect(connection)
            await asyncio.sleep(POLL_INTERVAL_S)


hub = WebSocketHub()
