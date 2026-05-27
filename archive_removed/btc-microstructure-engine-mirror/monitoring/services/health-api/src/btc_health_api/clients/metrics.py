"""metrics-exporter client. Fetches /api/snapshot JSON."""

from __future__ import annotations

from typing import Any

import httpx


class MetricsClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def snapshot(self) -> dict[str, Any] | None:
        try:
            r = await self._client.get(f"{self.base}/api/snapshot")
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def history(self) -> dict[str, list]:
        """Returns { file_basename: [[ts, rows], ...] } for the sparkline buffer."""
        try:
            r = await self._client.get(f"{self.base}/api/history/rows")
            if r.status_code == 200:
                return (r.json() or {}).get("history", {}) or {}
        except Exception:
            pass
        return {}

    async def preview(self, basename: str, rows: int = 100) -> dict[str, Any] | None:
        try:
            r = await self._client.get(f"{self.base}/api/preview/{basename}",
                                       params={"rows": str(rows)},
                                       timeout=10.0)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    async def preview_csv(self, basename: str, rows: int = 100_000) -> bytes | None:
        try:
            r = await self._client.get(f"{self.base}/api/preview/{basename}.csv",
                                       params={"rows": str(rows)},
                                       timeout=30.0)
            return r.content if r.status_code == 200 else None
        except Exception:
            return None

    async def healthy(self) -> bool:
        try:
            r = await self._client.get(f"{self.base}/healthz")
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
