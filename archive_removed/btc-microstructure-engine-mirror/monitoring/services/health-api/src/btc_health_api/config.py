"""Frozen, env-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _i(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _s(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Config:
    listen_host: str = field(default_factory=lambda: _s("LISTEN_HOST", "0.0.0.0"))
    listen_port: int = field(default_factory=lambda: _i("HEALTH_API_PORT", 8080))

    # upstream service URLs
    metrics_url: str = field(default_factory=lambda:
        _s("HEALTH_API_METRICS_URL", "http://metrics-exporter:9101"))
    alert_engine_url: str = field(default_factory=lambda:
        _s("HEALTH_API_ALERT_ENGINE_URL", "http://alert-engine:9102"))
    watchdog_url: str = field(default_factory=lambda:
        _s("HEALTH_API_WATCHDOG_URL", "http://watchdog:9103"))
    cadvisor_url: str = field(default_factory=lambda:
        _s("HEALTH_API_CADVISOR_URL", "http://cadvisor:8080"))
    node_exporter_url: str = field(default_factory=lambda:
        _s("HEALTH_API_NODE_EXPORTER_URL", "http://node-exporter:9100"))
    redis_url: str = field(default_factory=lambda:
        _s("HEALTH_API_REDIS_URL", "redis://redis:6379/0"))

    docker_socket: str = field(default_factory=lambda:
        _s("HEALTH_API_DOCKER_SOCKET", "/var/run/docker.sock"))

    # cache TTL for upstream snapshots (seconds). Pages refresh every
    # `refresh_interval_seconds` via HTMX; cache prevents stampedes.
    refresh_interval_seconds: int = field(default_factory=lambda:
        _i("HEALTH_API_REFRESH_INTERVAL_SECONDS", 5))
    upstream_timeout_seconds: float = field(default_factory=lambda:
        float(_s("HEALTH_API_UPSTREAM_TIMEOUT_SECONDS", "3")))

    log_level: str = field(default_factory=lambda: _s("LOG_LEVEL", "INFO").upper())
    service_name: str = "health-api"
    service_version: str = "0.2.0"

    # template/static dirs (resolved relative to package install)
    template_dir: Path = field(default_factory=lambda: Path(__file__).parent / "templates")
    static_dir:   Path = field(default_factory=lambda: Path(__file__).parent / "static")

    def validate(self) -> None:
        if not (0 < self.listen_port < 65536):
            raise ValueError("HEALTH_API_PORT out of range")
        if self.refresh_interval_seconds < 1:
            raise ValueError("HEALTH_API_REFRESH_INTERVAL_SECONDS must be >= 1")
