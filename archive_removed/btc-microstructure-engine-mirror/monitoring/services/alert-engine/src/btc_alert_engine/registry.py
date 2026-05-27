"""Prometheus metrics emitted by the engine itself."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(frozen=True)
class Metrics:
    registry: CollectorRegistry
    received: Counter
    emitted: Counter
    deduped: Counter
    active: Gauge
    cooldowns_active: Gauge
    redis_errors: Counter


def build_metrics() -> Metrics:
    r = CollectorRegistry(auto_describe=True)
    return Metrics(
        registry=r,
        received=Counter(
            "btc_alerts_received_total",
            "Total alerts received from Alertmanager",
            ["severity", "source"],
            registry=r,
        ),
        emitted=Counter(
            "btc_alerts_emitted_total",
            "Total alerts emitted to pubsub after dedup",
            ["severity", "domain"],
            registry=r,
        ),
        deduped=Counter(
            "btc_alerts_deduped_total",
            "Total alerts suppressed by cooldown / dedup",
            ["severity"],
            registry=r,
        ),
        active=Gauge(
            "btc_alerts_active",
            "Currently active (firing) alerts by severity",
            ["severity"],
            registry=r,
        ),
        cooldowns_active=Gauge(
            "btc_alert_engine_cooldowns_active",
            "Number of fingerprints currently in cooldown",
            registry=r,
        ),
        redis_errors=Counter(
            "btc_alert_engine_redis_errors_total",
            "Redis operation failures by op",
            ["op"],
            registry=r,
        ),
    )
