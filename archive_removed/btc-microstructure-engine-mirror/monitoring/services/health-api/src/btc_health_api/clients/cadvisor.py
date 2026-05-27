"""
cAdvisor client. Scrapes /metrics and groups CPU + memory per container
(uses the same tiny parser as NodeExporterClient — kept local for
zero-shared-state).
"""

from __future__ import annotations

import time

import httpx

from .node_exporter import _parse_metrics


_CACHE_TTL = 5.0   # seconds


class CAdvisorClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._cache: dict | None = None
        self._cache_ts: float = 0.0
        self._prev: dict[str, tuple[float, float]] = {}  # name -> (cpu_total_sec, ts) for rate

    async def per_container(self) -> dict[str, dict[str, float]]:
        """Returns { container_name: { cpu_user_pct, memory_bytes, memory_pct } }."""
        now = time.time()
        if self._cache is not None and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        try:
            r = await self._client.get(f"{self.base}/metrics")
            if r.status_code != 200:
                return self._cache or {}
        except Exception:
            return self._cache or {}

        m = _parse_metrics(r.text, {
            "container_cpu_usage_seconds_total",
            "container_memory_usage_bytes",
            "container_memory_working_set_bytes",
            "container_spec_memory_limit_bytes",
        })

        out: dict[str, dict[str, float]] = {}

        # CPU: compute rate against previous snapshot
        for labels, val in m["container_cpu_usage_seconds_total"]:
            name = labels.get("name") or labels.get("container_label_com_docker_compose_service")
            if not name or not name.startswith("btc_"):
                continue
            prev = self._prev.get(name)
            self._prev[name] = (val, now)
            if prev is None:
                continue
            dt = now - prev[1]
            if dt <= 0:
                continue
            cpu_pct = max(0.0, (val - prev[0]) / dt) * 100.0   # cores * 100
            out.setdefault(name, {})["cpu_pct"] = cpu_pct

        # memory: prefer working set, fall back to usage
        ws_by_name: dict[str, float] = {}
        for labels, val in m["container_memory_working_set_bytes"]:
            n = labels.get("name")
            if n and n.startswith("btc_"):
                ws_by_name[n] = val
        for labels, val in m["container_memory_usage_bytes"]:
            n = labels.get("name")
            if n and n.startswith("btc_"):
                ws_by_name.setdefault(n, val)
        for n, val in ws_by_name.items():
            out.setdefault(n, {})["memory_bytes"] = val

        self._cache = out
        self._cache_ts = now
        return out

    async def close(self) -> None:
        await self._client.aclose()
