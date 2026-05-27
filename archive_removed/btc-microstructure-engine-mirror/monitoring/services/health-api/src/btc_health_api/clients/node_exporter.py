"""
node-exporter client. Scrapes the text-format /metrics endpoint and
extracts a handful of host metrics we actually display. We do NOT
pull in the prometheus_client parser — line-based parsing of the few
metrics we need is < 30 lines and avoids the dependency.
"""

from __future__ import annotations

import httpx


def _parse_metrics(text: str, names: set[str]) -> dict[str, list[tuple[dict[str, str], float]]]:
    """Tiny text-format parser. Returns { metric_name: [(labels, value), ...] }.

    Skips HELP/TYPE lines, comment lines, and lines that don't match a
    name we care about. Labels are parsed naively (no escaped chars).
    """
    out: dict[str, list[tuple[dict[str, str], float]]] = {n: [] for n in names}
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        # split metric from value
        try:
            sep = line.rindex(" ")
        except ValueError:
            continue
        key, val_str = line[:sep], line[sep + 1:]
        try:
            val = float(val_str)
        except ValueError:
            continue
        labels: dict[str, str] = {}
        if "{" in key:
            name, rest = key.split("{", 1)
            name = name.strip()
            rest = rest.rstrip("}")
            for part in rest.split(","):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
        else:
            name = key.strip()
        if name in names:
            out[name].append((labels, val))
    return out


class NodeExporterClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def host_stats(self) -> dict | None:
        """Returns a structured host snapshot or None on failure."""
        try:
            r = await self._client.get(f"{self.base}/metrics")
            if r.status_code != 200:
                return None
            text = r.text
        except Exception:
            return None

        m = _parse_metrics(text, {
            "node_cpu_seconds_total",
            "node_memory_MemTotal_bytes",
            "node_memory_MemAvailable_bytes",
            "node_filesystem_size_bytes",
            "node_filesystem_avail_bytes",
            "node_load1",
            "node_load5",
            "node_load15",
            "node_filefd_allocated",
            "node_time_seconds",
            "node_boot_time_seconds",
        })

        # CPU busy: 1 - (sum idle / sum total) is a snapshot; we report the
        # idle ratio as is.
        total_cpu = 0.0
        idle_cpu = 0.0
        for labels, val in m["node_cpu_seconds_total"]:
            total_cpu += val
            if labels.get("mode") == "idle":
                idle_cpu += val
        cpu_busy = 1.0 - (idle_cpu / total_cpu) if total_cpu > 0 else None

        mem_total = m["node_memory_MemTotal_bytes"][0][1] if m["node_memory_MemTotal_bytes"] else None
        mem_avail = m["node_memory_MemAvailable_bytes"][0][1] if m["node_memory_MemAvailable_bytes"] else None
        mem_used_ratio = ((mem_total - mem_avail) / mem_total) if mem_total and mem_avail else None

        # find /host filesystem (mountpoint=/host)
        disk_total = disk_free = None
        for labels, val in m["node_filesystem_size_bytes"]:
            if labels.get("mountpoint") == "/host":
                disk_total = val
                break
        for labels, val in m["node_filesystem_avail_bytes"]:
            if labels.get("mountpoint") == "/host":
                disk_free = val
                break
        disk_free_ratio = (disk_free / disk_total) if disk_total and disk_free else None

        load1 = m["node_load1"][0][1] if m["node_load1"] else None
        load5 = m["node_load5"][0][1] if m["node_load5"] else None
        load15 = m["node_load15"][0][1] if m["node_load15"] else None

        boot = m["node_boot_time_seconds"][0][1] if m["node_boot_time_seconds"] else None
        now = m["node_time_seconds"][0][1] if m["node_time_seconds"] else None
        host_uptime = (now - boot) if (now and boot) else None

        return {
            "cpu_busy_ratio": cpu_busy,
            "memory_total_bytes": mem_total,
            "memory_available_bytes": mem_avail,
            "memory_used_ratio": mem_used_ratio,
            "disk_total_bytes": disk_total,
            "disk_free_bytes": disk_free,
            "disk_free_ratio": disk_free_ratio,
            "load1": load1,
            "load5": load5,
            "load15": load15,
            "host_uptime_seconds": host_uptime,
        }

    async def close(self) -> None:
        await self._client.aclose()
