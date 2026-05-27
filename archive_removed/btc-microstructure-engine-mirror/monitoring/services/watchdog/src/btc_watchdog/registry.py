"""Prometheus metrics emitted by the watchdog itself."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(frozen=True)
class Metrics:
    registry: CollectorRegistry
    restarts: Counter
    skipped: Counter
    errors: Counter
    circuit_state: Gauge
    budget_used: Gauge
    last_poll_age: Gauge


def build_metrics() -> Metrics:
    r = CollectorRegistry(auto_describe=True)
    return Metrics(
        registry=r,
        restarts=Counter(
            "btc_watchdog_restarts_total",
            "Container restarts performed by the watchdog",
            ["target", "policy", "result"],
            registry=r,
        ),
        skipped=Counter(
            "btc_watchdog_skipped_total",
            "Restart actions skipped (budget / circuit / dry-run / not-allowed)",
            ["target", "reason"],
            registry=r,
        ),
        errors=Counter(
            "btc_watchdog_errors_total",
            "Errors encountered by the watchdog",
            ["op"],
            registry=r,
        ),
        circuit_state=Gauge(
            "btc_watchdog_circuit_open",
            "1 if the circuit breaker is open (no restarts allowed) for this feed",
            ["feed"],
            registry=r,
        ),
        budget_used=Gauge(
            "btc_watchdog_restart_budget_used",
            "Restarts performed in the current rolling 1h window",
            registry=r,
        ),
        last_poll_age=Gauge(
            "btc_watchdog_last_poll_age_seconds",
            "Seconds since the last full poll iteration",
            registry=r,
        ),
    )
