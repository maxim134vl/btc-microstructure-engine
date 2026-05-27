"""Configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _i(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _s(name: str, default: str) -> str:
    return os.environ.get(name) or default


# Containers we are allowed to restart. Anything outside this allowlist is
# logged but never touched. Patterns are simple substring matches.
RESTART_ALLOWLIST = (
    "btc_pipeline",
    "btc_binance_feed",
    "btc_multi_exchange",
    "btc_orderbook",
    "btc_liquidations",
    "btc_oi",
    "btc_intraday_flow",
)


@dataclass(frozen=True)
class Config:
    listen_host: str = field(default_factory=lambda: _s("LISTEN_HOST", "0.0.0.0"))
    listen_port: int = field(default_factory=lambda: _i("WATCHDOG_PORT", 9103))

    # Direct unix-socket mount; the proxy is gone (see SECURITY.md for the
    # tradeoff: ro mount + restart-only docker SDK surface).
    docker_host: str = field(
        default_factory=lambda: _s("WATCHDOG_DOCKER_HOST", "unix:///var/run/docker.sock")
    )
    metrics_url: str = field(
        default_factory=lambda: _s("WATCHDOG_METRICS_URL", "http://metrics-exporter:9101")
    )

    poll_interval_seconds: int = field(default_factory=lambda: _i("WATCHDOG_POLL_INTERVAL_SECONDS", 30))

    # ---- policy thresholds ----
    stall_threshold_seconds: int = field(
        default_factory=lambda: _i("WATCHDOG_STALL_THRESHOLD_SECONDS", 120)
    )
    dead_collector_threshold_seconds: int = field(
        default_factory=lambda: _i("WATCHDOG_DEAD_COLLECTOR_THRESHOLD_SECONDS", 90)
    )
    reconnect_storm_threshold: float = field(
        default_factory=lambda: float(_s("WATCHDOG_RECONNECT_STORM_THRESHOLD", "10"))
    )

    # ---- budgets ----
    restart_budget_per_hour: int = field(
        default_factory=lambda: _i("WATCHDOG_RESTART_BUDGET_PER_HOUR", 10)
    )
    circuit_cooloff_seconds: int = field(
        default_factory=lambda: _i("WATCHDOG_CIRCUIT_COOLOFF_SECONDS", 900)
    )

    log_level: str = field(default_factory=lambda: _s("LOG_LEVEL", "INFO").upper())
    service_name: str = "watchdog"
    service_version: str = "0.1.0"

    # ---- safety toggles ----
    enabled: bool = field(
        default_factory=lambda: _s("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    dry_run: bool = field(
        default_factory=lambda: _s("WATCHDOG_DRY_RUN", "false").lower() in ("1", "true", "yes")
    )

    def validate(self) -> None:
        if self.poll_interval_seconds < 5:
            raise ValueError("WATCHDOG_POLL_INTERVAL_SECONDS must be >= 5")
        if self.restart_budget_per_hour < 0:
            raise ValueError("WATCHDOG_RESTART_BUDGET_PER_HOUR must be >= 0")
        if not (0 < self.listen_port < 65536):
            raise ValueError("WATCHDOG_PORT out of range")
