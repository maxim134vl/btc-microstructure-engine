"""
Docker socket client over httpx with a UDS transport.

Why httpx + UDS rather than docker-py: docker-py is sync, uses a fixed
API version that Docker Desktop 4.57+ rejects, and pulls in heavyweight
deps. Plain JSON HTTP over the socket is < 100 lines and works fine.

We use unversioned endpoints (/containers/json, /containers/<id>/json,
/containers/<id>/logs, /containers/<id>/restart, /info) which Docker
Engine has supported since v1 and Docker Desktop still accepts.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import httpx


class DockerClient:
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://docker",
            timeout=timeout,
        )

    async def containers(self, all_: bool = True) -> list[dict]:
        """List all containers with their labels and status."""
        try:
            r = await self._client.get(
                "/containers/json", params={"all": "true" if all_ else "false"}
            )
            if r.status_code != 200:
                return []
            return r.json()
        except Exception:
            return []

    async def inspect(self, name_or_id: str) -> dict | None:
        try:
            r = await self._client.get(f"/containers/{name_or_id}/json")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    async def info(self) -> dict | None:
        try:
            r = await self._client.get("/info")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    async def restart(self, name_or_id: str, timeout_s: int = 10) -> bool:
        try:
            r = await self._client.post(
                f"/containers/{name_or_id}/restart",
                params={"t": str(timeout_s)},
                timeout=30.0,
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    async def logs_tail(self, name_or_id: str, lines: int = 100) -> str:
        """Return the last `lines` log lines as text (stdout+stderr)."""
        try:
            r = await self._client.get(
                f"/containers/{name_or_id}/logs",
                params={"stdout": "true", "stderr": "true",
                        "tail": str(lines), "timestamps": "false"},
                headers={"Accept": "application/vnd.docker.raw-stream"},
            )
            if r.status_code != 200:
                return ""
            return _decode_docker_logs(r.content)
        except Exception:
            return ""

    async def logs_stream(
        self, name_or_id: str, tail: int = 50
    ) -> AsyncIterator[str]:
        """Stream new log lines from the container. Caller iterates."""
        url = f"/containers/{name_or_id}/logs?stdout=true&stderr=true&follow=true&tail={tail}&timestamps=false"
        async with self._client.stream("GET", url, timeout=None) as r:
            if r.status_code != 200:
                return
            async for chunk in r.aiter_bytes():
                yield _decode_docker_logs(chunk)

    async def close(self) -> None:
        await self._client.aclose()


def _decode_docker_logs(raw: bytes) -> str:
    """
    Docker multiplexes stdout/stderr in a framed format when no TTY is
    allocated:  [stream_type(1)][0(3)][size(4)][payload(size)]
    For TTY containers it's just raw bytes.
    Try framed first; fall back to raw decode.
    """
    out = bytearray()
    i = 0
    n = len(raw)
    while i + 8 <= n:
        stream = raw[i]
        if stream not in (0, 1, 2):
            # not framed; treat rest as raw
            out.extend(raw[i:])
            break
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        if i + 8 + size > n:
            # incomplete frame; emit what we have
            out.extend(raw[i + 8:])
            break
        out.extend(raw[i + 8:i + 8 + size])
        i += 8 + size
    if i == 0:
        # nothing consumed as frame; treat all as raw
        out.extend(raw)
    try:
        return out.decode("utf-8", errors="replace")
    except Exception:
        return ""


def container_compact(c: dict) -> dict:
    """Compact representation suitable for templates."""
    labels = c.get("Labels", {}) or {}
    name = c.get("Names", ["?"])[0].lstrip("/")
    started = c.get("Created", 0)            # unix epoch (seconds)
    state = c.get("State", "?")
    status = c.get("Status", "?")
    image = c.get("Image", "?")
    health = ""
    if "(healthy)" in status:
        health = "healthy"
    elif "(unhealthy)" in status:
        health = "unhealthy"
    elif "(health: starting)" in status:
        health = "starting"
    uptime = ""
    if state == "running" and started:
        delta_s = max(0, int(datetime.now().timestamp() - started))
        uptime = _fmt_uptime(delta_s)
    return {
        "id": c.get("Id", "")[:12],
        "name": name,
        "image": image,
        "state": state,
        "status": status,
        "health": health,
        "uptime": uptime,
        "compose_project": labels.get("com.docker.compose.project", ""),
        "compose_service": labels.get("com.docker.compose.service", ""),
    }


def _fmt_uptime(s: int) -> str:
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s // 60}m"
    if s < 86400: return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"
