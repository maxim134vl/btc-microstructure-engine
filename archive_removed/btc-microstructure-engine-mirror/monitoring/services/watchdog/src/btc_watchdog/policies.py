"""
Decision logic. Pure functions that take a Prometheus snapshot and return
a list of `Action`s. The orchestrator in app.py is responsible for applying
budget / circuit / dry-run gates before executing them.

This split lets us unit-test policies without docker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ActionKind = Literal["restart", "trip_circuit"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target: str           # container name OR feed name (for circuit)
    policy: str           # policy that produced this action
    reason: str           # human-readable reason for audit log


def decide_stall(iter_age_seconds: float | None, threshold: int) -> list[Action]:
    """If the pipeline runtime has been silent past threshold, restart it."""
    if iter_age_seconds is None or iter_age_seconds < threshold:
        return []
    return [Action(
        kind="restart",
        target="btc_pipeline",
        policy="stall-detect",
        reason=f"runtime iter age {iter_age_seconds:.0f}s >= {threshold}s",
    )]


def decide_dead_collector(up_vector: dict[str, float], threshold_passed: bool) -> list[Action]:
    """
    For each collector with up==0 long enough, propose a restart.

    `up_vector`: {container_name: 0|1}. The orchestrator builds this by
    correlating Prometheus `up{job=...}` with the actual container name; the
    policy doesn't need to know about Prom internals.

    `threshold_passed`: caller pre-computed whether the "stayed down for >N
    seconds" condition is true for these entries. Keeps the policy stateless.
    """
    actions: list[Action] = []
    if not threshold_passed:
        return actions
    for name, up in up_vector.items():
        if up != 0:
            continue
        actions.append(Action(
            kind="restart",
            target=name,
            policy="dead-collector",
            reason=f"container {name} reported up=0 past threshold",
        ))
    return actions


def decide_reconnect_storm(
    reconnects_per_5m: dict[str, float], threshold: float
) -> list[Action]:
    """If any feed reconnects too fast, trip its circuit breaker."""
    actions: list[Action] = []
    for feed, rate in reconnects_per_5m.items():
        if rate >= threshold:
            actions.append(Action(
                kind="trip_circuit",
                target=feed,
                policy="reconnect-storm",
                reason=f"reconnect rate {rate:.2f}/5m >= {threshold}/5m",
            ))
    return actions
