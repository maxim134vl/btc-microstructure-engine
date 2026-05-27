"""
Composite aggregator. Pulls from every upstream client and produces a
single 'view model' used by templates. Caches per-request via FastAPI's
app.state; for HTMX-driven refreshes the latency budget is ~200 ms total.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .clients import (
    AlertsClient,
    CAdvisorClient,
    DockerClient,
    MetricsClient,
    NodeExporterClient,
    WatchdogClient,
)
from .clients.docker_api import container_compact


class Aggregator:
    def __init__(
        self,
        metrics: MetricsClient,
        alerts: AlertsClient,
        watchdog: WatchdogClient,
        cadvisor: CAdvisorClient,
        node: NodeExporterClient,
        docker: DockerClient,
    ) -> None:
        self.metrics = metrics
        self.alerts = alerts
        self.watchdog = watchdog
        self.cadvisor = cadvisor
        self.node = node
        self.docker = docker

    # ---- raw fetches (run in parallel) ----------------------------------
    async def fetch_all(self) -> dict[str, Any]:
        """Fan out to every upstream once. Used by every page render."""
        snapshot, alerts, host, containers, per_ctr, history = await asyncio.gather(
            self.metrics.snapshot(),
            self.alerts.active(),
            self.node.host_stats(),
            self.docker.containers(all_=True),
            self.cadvisor.per_container(),
            self.metrics.history(),
            return_exceptions=False,
        )
        all_containers = [container_compact(c) for c in (containers or [])]
        # split: engine = data plane (what we monitor) vs obs = our own stack
        engine = [c for c in all_containers if c["name"].startswith("btc_")
                  and not c["name"].startswith("btc_obs_")]
        obs    = [c for c in all_containers if c["name"].startswith("btc_obs_")]
        return {
            "snapshot": snapshot or _empty_snapshot(),
            "alerts": alerts or [],
            "host": host or {},
            "containers": all_containers,            # kept for any callers; UI uses split
            "engine_containers": sorted(engine, key=lambda c: c["name"]),
            "obs_containers":    sorted(obs,    key=lambda c: c["name"]),
            "per_container_rt": per_ctr or {},
            "history": history or {},                # { basename: [[ts, rows], ...] }
            "ts": time.time(),
        }

    # ---- view models -----------------------------------------------------
    def dashboard_view(self, data: dict[str, Any]) -> dict[str, Any]:
        snap = data["snapshot"]
        alerts = data["alerts"]
        host = data["host"]
        containers = data["containers"]

        # Engine = the data plane we're monitoring.
        # Obs   = the observability stack itself (shown only as a self-status
        #         pill in the topbar — operator cares about engine, not us).
        engine = [c for c in containers if c["name"].startswith("btc_")
                  and not c["name"].startswith("btc_obs_")]
        obs    = [c for c in containers if c["name"].startswith("btc_obs_")]

        e_running = sum(1 for c in engine if c["state"] == "running")
        e_total   = len(engine)
        e_healthy = sum(1 for c in engine if c["health"] == "healthy")

        obs_running = sum(1 for c in obs if c["state"] == "running")
        obs_healthy = sum(1 for c in obs if c["health"] == "healthy")
        obs_total   = len(obs)

        # parquet rollup — only count "live" + "rest" kinds for health
        parquets = snap.get("parquets", []) or []
        live_files = [p for p in parquets if p.get("kind") in ("live", "rest")]
        stale = [p for p in live_files
                 if (p.get("age_seconds") or 0) > _stale_threshold(p)]
        invalid = [p for p in live_files if p.get("schema_valid") is False]

        # alert breakdown
        sev_counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
        for a in alerts:
            sev_counts[a.get("severity", "info")] = sev_counts.get(a.get("severity", "info"), 0) + 1

        rt = snap.get("runtime") or {}
        runtime_age = rt.get("last_iter_age_seconds")
        runtime_status = _runtime_status(runtime_age)

        # overall — purely about engine + its data
        overall = "ok"
        if sev_counts["critical"] > 0 or runtime_status == "down" or invalid or len(stale) >= 2:
            overall = "down"
        elif sev_counts["warning"] > 0 or runtime_status == "degraded" or stale:
            overall = "degraded"

        return {
            "overall": overall,
            "stats": {
                "containers_running": e_running,
                "containers_total":   e_total,
                "containers_healthy": e_healthy,
                "alerts_total":    len(alerts),
                "alerts_critical": sev_counts["critical"],
                "alerts_warning":  sev_counts["warning"],
                "alerts_info":     sev_counts["info"],
                "parquets_total":   len(live_files),
                "parquets_stale":   len(stale),
                "parquets_invalid": len(invalid),
                "runtime_age_seconds": runtime_age,
                "runtime_status":   runtime_status,
                "disk_free_ratio":   host.get("disk_free_ratio"),
                "memory_used_ratio": host.get("memory_used_ratio"),
                "cpu_busy_ratio":    host.get("cpu_busy_ratio"),
                "load1":             host.get("load1"),
                "host_uptime_seconds": host.get("host_uptime_seconds"),
            },
            "obs": {
                "running": obs_running,
                "total":   obs_total,
                "healthy": obs_healthy,
                "status":  "ok" if obs_running == obs_total == obs_healthy
                           else "degraded" if obs_running == obs_total else "down",
            },
            "domains": [
                {"name": "pipeline",
                 "status": runtime_status,
                 "summary": _fmt_age(runtime_age) + " since last iter"
                            if runtime_age is not None else "no data"},
                {"name": "dataflow",
                 "status": _data_status(stale, invalid),
                 "summary": _data_summary(live_files, stale, invalid)},
                {"name": "feed",
                 "status": _feed_status(live_files),
                 "summary": _feed_summary(live_files)},
                {"name": "system",
                 "status": _system_status(host),
                 "summary": _system_summary(host)},
                {"name": "research",
                 "status": _research_status(snap),
                 "summary": _research_summary(snap)},
            ],
        }


# ---- helpers --------------------------------------------------------------

def _runtime_status(age: float | None) -> str:
    if age is None: return "unknown"
    if age >= 120: return "down"
    if age >= 60:  return "degraded"
    return "ok"


# live = ws collectors (sub-second writes); rest = REST collectors (~30-60s)
LIVE_STALE_S = 60.0
REST_STALE_S = 120.0


def _stale_threshold(p: dict) -> float:
    return LIVE_STALE_S if p.get("kind") == "live" else REST_STALE_S


def _data_status(stale: list, invalid: list) -> str:
    if invalid: return "down"
    if len(stale) >= 2: return "down"
    if stale: return "degraded"
    return "ok"


def _data_summary(live_files: list, stale: list, invalid: list) -> str:
    if not live_files:
        return "no tracked producers yet"
    bits = [f"{len(live_files)} tracked"]
    if stale:   bits.append(f"{len(stale)} stale")
    if invalid: bits.append(f"{len(invalid)} invalid")
    return " · ".join(bits) if (stale or invalid) else f"{len(live_files)} producers ok"


def _feed_status(parquets: list) -> str:
    # only judge truly live (sub-second) feeds
    live = [p for p in parquets if p.get("kind") == "live"]
    if not live: return "unknown"
    worst = 0.0
    for p in live:
        a = p.get("age_seconds") or 0.0
        if a > worst: worst = a
    if worst >= 60: return "down"
    if worst >= 30: return "degraded"
    return "ok"


def _feed_summary(parquets: list) -> str:
    live = [p for p in parquets if p.get("kind") == "live"]
    if not live: return "no live feeds detected"
    parts = [f"{(p.get('producer') or '?')}: {_fmt_age(p.get('age_seconds'))}"
             for p in live[:3]]
    return " · ".join(parts)


def _system_status(host: dict) -> str:
    if not host: return "unknown"
    if (host.get("disk_free_ratio") or 1.0) < 0.05: return "down"
    if (host.get("disk_free_ratio") or 1.0) < 0.15: return "degraded"
    if (host.get("memory_used_ratio") or 0.0) > 0.85: return "degraded"
    if (host.get("cpu_busy_ratio") or 0.0) > 0.9: return "degraded"
    return "ok"


def _system_summary(host: dict) -> str:
    if not host: return "node-exporter unreachable"
    bits = []
    if host.get("cpu_busy_ratio") is not None:
        bits.append(f"cpu {host['cpu_busy_ratio']*100:.0f}%")
    if host.get("memory_used_ratio") is not None:
        bits.append(f"mem {host['memory_used_ratio']*100:.0f}%")
    if host.get("disk_free_ratio") is not None:
        bits.append(f"disk {host['disk_free_ratio']*100:.0f}% free")
    return " · ".join(bits) if bits else "no data"


def _research_status(snap: dict) -> str:
    feats = snap.get("features") or []
    nan_max = max((f.get("nan_ratio") or 0.0) for f in feats) if feats else 0.0
    inf_sum = sum((f.get("inf_count") or 0) for f in feats)
    entropy = (snap.get("regime") or {}).get("entropy_bits")
    if nan_max > 0.10: return "down"
    if nan_max > 0.01 or inf_sum > 0: return "degraded"
    if entropy is not None and entropy < 0.1: return "degraded"
    return "ok" if feats else "unknown"


def _research_summary(snap: dict) -> str:
    feats = snap.get("features") or []
    nan_max = max((f.get("nan_ratio") or 0.0) for f in feats) if feats else 0.0
    inf_sum = sum((f.get("inf_count") or 0) for f in feats)
    entropy = (snap.get("regime") or {}).get("entropy_bits")
    parts = []
    if nan_max:        parts.append(f"NaN max {nan_max*100:.1f}%")
    if inf_sum:        parts.append(f"{int(inf_sum)} inf")
    if entropy is not None: parts.append(f"entropy {entropy:.2f} bit")
    return " · ".join(parts) if parts else "all features clean"


def _fmt_age(s: float | None) -> str:
    if s is None: return "—"
    if s < 60: return f"{s:.0f}s"
    if s < 3600: return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


def _empty_snapshot() -> dict:
    return {"parquets": [], "features": [], "regime": {}, "runtime": {}, "self": {}}
