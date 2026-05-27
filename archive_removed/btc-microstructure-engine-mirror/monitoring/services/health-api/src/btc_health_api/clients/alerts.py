"""alert-engine client."""

from __future__ import annotations

from typing import Any

import httpx


class AlertsClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def active(self) -> list[dict[str, Any]]:
        try:
            r = await self._client.get(f"{self.base}/api/alerts/active")
            if r.status_code == 200:
                doc = r.json()
                return doc.get("alerts", []) or []
            return []
        except Exception:
            return []

    async def healthy(self) -> bool:
        try:
            r = await self._client.get(f"{self.base}/healthz")
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
