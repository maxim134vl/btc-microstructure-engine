"""Entrypoint — polls metrics-exporter snapshot + applies policies + executes."""

from __future__ import annotations

import asyncio
import signal
import sys
import time

import httpx
from aiohttp import web

try:
    import uvloop
except ImportError:
    uvloop = None  # type: ignore[assignment]

from .config import RESTART_ALLOWLIST, Config
from .docker_client import DockerCtl
from .logging import configure_logging
from .policies import Action, decide_reconnect_storm, decide_stall
from .registry import build_metrics
from .server import AuditLog, make_app
from .state import CircuitBreaker, RestartBudget


async def main_async() -> int:
    cfg = Config()
    cfg.validate()
    log = configure_logging(cfg)
    log.info("startup",
             enabled=cfg.enabled,
             dry_run=cfg.dry_run,
             docker_host=cfg.docker_host,
             metrics_url=cfg.metrics_url,
             budget_per_hour=cfg.restart_budget_per_hour)

    metrics = build_metrics()
    budget = RestartBudget(cfg.restart_budget_per_hour)
    circuits = CircuitBreaker(cfg.circuit_cooloff_seconds)
    audit = AuditLog()
    state: dict = {"last_poll_ts": None, "last_snapshot_ts": None}

    docker_ctl = DockerCtl(cfg.docker_host, log)
    http_client = httpx.AsyncClient(timeout=5.0)

    app = make_app(cfg, metrics, budget, circuits, audit, state)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, cfg.listen_host, cfg.listen_port)
    await site.start()
    log.info("server.listening", port=cfg.listen_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    poller = asyncio.create_task(
        _poll_loop(cfg, http_client, docker_ctl, metrics, budget, circuits, audit, state, log, stop),
        name="poll_loop",
    )

    await stop.wait()
    log.info("shutdown.begin")
    poller.cancel()
    with __import__("contextlib").suppress(Exception):
        await poller
    await runner.cleanup()
    await http_client.aclose()
    await docker_ctl.close()
    log.info("shutdown.complete")
    return 0


async def _poll_loop(
    cfg, http, docker_ctl, metrics, budget, circuits, audit, state, log, stop
) -> None:
    while not stop.is_set():
        try:
            await _tick(cfg, http, docker_ctl, metrics, budget, circuits, audit, state, log)
        except Exception:
            metrics.errors.labels("tick").inc()
            log.exception("tick.error")
        state["last_poll_ts"] = time.time()
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.poll_interval_seconds)
        except asyncio.TimeoutError:
            continue


async def _tick(
    cfg, http, docker_ctl, metrics, budget, circuits, audit, state, log
) -> None:
    snapshot = await _fetch_snapshot(cfg, http, metrics)
    if snapshot is None:
        return
    state["last_snapshot_ts"] = time.time()

    runtime = snapshot.get("runtime") or {}
    iter_age = runtime.get("last_iter_age_seconds")

    # reconnect-storm input is empty in v0.2 (no per-feed reconnect counter
    # yet); kept as a no-op placeholder so the policy signature stays.
    reconnect_rates: dict[str, float] = {}

    actions: list[Action] = []
    actions += decide_stall(iter_age, cfg.stall_threshold_seconds)
    actions += decide_reconnect_storm(reconnect_rates, cfg.reconnect_storm_threshold)

    for action in actions:
        await _apply(cfg, action, docker_ctl, metrics, budget, circuits, audit, log)


async def _fetch_snapshot(cfg: Config, http: httpx.AsyncClient, metrics) -> dict | None:
    try:
        r = await http.get(f"{cfg.metrics_url}/api/snapshot")
        if r.status_code != 200:
            metrics.errors.labels("snapshot_http").inc()
            return None
        return r.json()
    except Exception:
        metrics.errors.labels("snapshot_exception").inc()
        return None


async def _apply(
    cfg, action: Action, docker_ctl, metrics, budget, circuits, audit, log
) -> None:
    base = {
        "actor": "watchdog",
        "policy": action.policy,
        "target": action.target,
        "reason": action.reason,
        "kind": action.kind,
    }

    if not cfg.enabled:
        metrics.skipped.labels(action.target, "disabled").inc()
        audit.add({**base, "outcome": "skipped", "skip_reason": "disabled"})
        return

    if action.kind == "trip_circuit":
        if circuits.is_open(action.target):
            metrics.skipped.labels(action.target, "circuit_already_open").inc()
            return
        circuits.trip(action.target)
        metrics.circuit_state.labels(action.target).set(1)
        audit.add({**base, "outcome": "tripped"})
        log.warning("circuit.tripped", **base)
        return

    if action.kind == "restart":
        if not any(action.target.startswith(p) for p in RESTART_ALLOWLIST):
            metrics.skipped.labels(action.target, "not_allowlisted").inc()
            audit.add({**base, "outcome": "skipped", "skip_reason": "not_allowlisted"})
            return

        if circuits.is_open(action.target):
            metrics.skipped.labels(action.target, "circuit_open").inc()
            audit.add({**base, "outcome": "skipped", "skip_reason": "circuit_open"})
            return

        if not budget.try_consume():
            metrics.skipped.labels(action.target, "budget_exhausted").inc()
            audit.add({**base, "outcome": "skipped", "skip_reason": "budget_exhausted"})
            log.warning("audit.container.skip", **base, skip_reason="budget_exhausted")
            return

        if cfg.dry_run:
            metrics.skipped.labels(action.target, "dry_run").inc()
            audit.add({**base, "outcome": "skipped", "skip_reason": "dry_run"})
            log.info("audit.container.restart", **base, outcome="dry_run")
            return

        ok = await docker_ctl.restart(action.target)
        result = "ok" if ok else "fail"
        metrics.restarts.labels(action.target, action.policy, result).inc()
        audit.add({**base, "outcome": result})
        log.info("audit.container.restart", **base, outcome=result)


def main() -> int:
    if uvloop is not None:
        uvloop.install()
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
