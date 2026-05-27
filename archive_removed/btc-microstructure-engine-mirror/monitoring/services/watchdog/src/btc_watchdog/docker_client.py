"""
Wraps the docker SDK against the socket-proxy. Only `restart()` is exposed —
the rest of the SDK is *intentionally* not used. Even though socket-proxy
allowlists the endpoints, this module's narrow surface is the second line
of defense.
"""

from __future__ import annotations

import asyncio

import docker

import structlog


class DockerCtl:
    def __init__(self, base_url: str, log: structlog.stdlib.BoundLogger) -> None:
        # docker.DockerClient is sync; we run calls in a thread pool.
        self._client = docker.DockerClient(base_url=base_url, timeout=10)
        self.log = log.bind(component="docker")

    async def restart(self, container_name: str, timeout: int = 10) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._restart_sync, container_name, timeout)
            return True
        except docker.errors.NotFound:
            self.log.warning("docker.not_found", target=container_name)
            return False
        except Exception:
            self.log.exception("docker.restart_failed",
                               target=container_name)
            return False

    def _restart_sync(self, container_name: str, timeout: int) -> None:
        c = self._client.containers.get(container_name)
        c.restart(timeout=timeout)

    async def list_btc_containers(self) -> list[dict]:
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, self._list_sync)
            return data
        except Exception:
            self.log.exception("docker.list_failed")
            return []

    def _list_sync(self) -> list[dict]:
        containers = self._client.containers.list(all=True)
        out = []
        for c in containers:
            if not c.name.startswith("btc_"):
                continue
            out.append({"name": c.name, "status": c.status, "id": c.id[:12]})
        return out

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._client.close)
