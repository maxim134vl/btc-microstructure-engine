"""Frozen, env-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _i(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _s(name: str, default: str) -> str:
    return os.environ.get(name) or default


# Per-severity defaults. Override via env if needed.
DEFAULT_COOLDOWNS: dict[str, int] = {
    "critical": 60,
    "warning": 300,
    "info": 900,
    "default": 300,
}


@dataclass(frozen=True)
class Config:
    listen_host: str = field(default_factory=lambda: _s("LISTEN_HOST", "0.0.0.0"))
    listen_port: int = field(default_factory=lambda: _i("ALERT_ENGINE_PORT", 9102))

    redis_url: str = field(default_factory=lambda: _s("ALERT_ENGINE_REDIS_URL", "redis://redis:6379/0"))
    metrics_url: str = field(default_factory=lambda: _s("ALERT_ENGINE_METRICS_URL", "http://metrics-exporter:9101"))

    eval_interval_seconds: int = field(
        default_factory=lambda: _i("ALERT_ENGINE_EVAL_INTERVAL_SECONDS", 15)
    )
    cooldown_default_seconds: int = field(
        default_factory=lambda: _i("ALERT_ENGINE_COOLDOWN_DEFAULT_SECONDS", 300)
    )

    log_level: str = field(default_factory=lambda: _s("LOG_LEVEL", "INFO").upper())
    service_name: str = "alert-engine"
    service_version: str = "0.2.0"

    pubsub_channel: str = field(default_factory=lambda: _s("ALERT_ENGINE_PUBSUB_CHANNEL", "alerts.live"))

    def cooldown_for(self, severity: str) -> int:
        return DEFAULT_COOLDOWNS.get(severity, self.cooldown_default_seconds)

    def validate(self) -> None:
        if self.cooldown_default_seconds < 1:
            raise ValueError("cooldown_default_seconds must be >= 1")
        if self.eval_interval_seconds < 5:
            raise ValueError("ALERT_ENGINE_EVAL_INTERVAL_SECONDS must be >= 5")
        if not (0 < self.listen_port < 65536):
            raise ValueError("ALERT_ENGINE_PORT out of range")
