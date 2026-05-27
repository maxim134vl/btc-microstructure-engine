"""watchdog client (audit log + circuit-breaker queries)."""

from __future__ import annotations

from typing import Any

import httpx


class WatchdogClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def audit(self, since: float | None = None) -> list[dict[str, Any]]:
        try:
            params = {"since": str(since)} if since is not None else None
            r = await self._client.get(f"{self.base}/api/audit", params=params)
            if r.status_code == 200:
                return (r.json() or {}).get("audit", []) or []
            return []
        except Exception:
            return []

    async def circuit_list(self) -> dict[str, float]:
        try:
            r = await self._client.get(f"{self.base}/api/circuit/list")
            if r.status_code == 200:
                return (r.json() or {}).get("open", {}) or {}
            return {}
        except Exception:
            return {}

    async def healthy(self) -> bool:
        try:
            r = await self._client.get(f"{self.base}/healthz")
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
