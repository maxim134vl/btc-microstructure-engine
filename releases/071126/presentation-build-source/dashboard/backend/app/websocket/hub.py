"""WebSocket delivery of ready publications; no analytics or worker executors."""
from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from app.transport_config import POLL_INTERVAL_S
from app.services.published_transport import build_published_snapshot

class WebSocketHub:
    def __init__(self):
        self.connections=set(); self._task=None; self._latest={}
        self._clients=asyncio.Event(); self._versions={}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # Fresh read, never replay _latest from a previous connection.
        snapshot=await build_published_snapshot()
        await websocket.send_text(json.dumps({'type':'snapshot','data':snapshot},allow_nan=False))
        self.connections.add(websocket)
        self._versions[websocket]=snapshot['transport']['version']
        self._latest=snapshot
        self._clients.set()

    def disconnect(self, websocket):
        self.connections.discard(websocket); self._versions.pop(websocket,None)
        if not self.connections: self._clients.clear(); self._latest={}

    async def start(self):
        if self._task is None:
            # Each ASGI lifespan owns its event loop; never retain a loop-bound Event.
            self._clients=asyncio.Event()
            if self.connections: self._clients.set()
            self._task=asyncio.create_task(self._poll_loop(),name='ops-publication-delivery')

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task=None
        self.connections.clear();self._versions.clear();self._latest={};self._clients.clear()

    async def _poll_loop(self):
        while True:
            await self._clients.wait()
            await asyncio.sleep(POLL_INTERVAL_S)
            if not self.connections: continue
            try:
                snapshot=await build_published_snapshot()
                self._latest=snapshot
                version=snapshot['transport']['version']
                payload=None
                for connection in tuple(self.connections):
                    if self._versions.get(connection)==version: continue
                    if payload is None: payload=json.dumps({'type':'snapshot','data':snapshot},allow_nan=False)
                    try:
                        await connection.send_text(payload);self._versions[connection]=version
                    except Exception: self.disconnect(connection)
            except Exception as error:
                payload=json.dumps({'type':'error','message':str(error)})
                for connection in tuple(self.connections):
                    try: await connection.send_text(payload)
                    except Exception: self.disconnect(connection)

hub=WebSocketHub()
