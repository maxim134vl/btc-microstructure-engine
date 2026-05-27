"""Entrypoint — periodic self-evaluating alert loop."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis_async
from aiohttp import web

try:
    import uvloop
except ImportError:
    uvloop = None  # type: ignore[assignment]

from .config import Config
from .evaluator import Alert, evaluate_all
from .logging import configure_logging
from .policies import cooldown_seconds
from .registry import build_metrics
from .server import make_app
from .state import AlertState, fingerprint


async def main_async() -> int:
    cfg = Config()
    cfg.validate()
    log = configure_logging(cfg)
    log.info("startup",
             port=cfg.listen_port,
             redis=cfg.redis_url,
             metrics_url=cfg.metrics_url,
             eval_interval=cfg.eval_interval_seconds)

    metrics = build_metrics()
    redis_client = redis_async.from_url(
        cfg.redis_url, encoding="utf-8", decode_responses=True,
        socket_connect_timeout=5, socket_keepalive=True, health_check_interval=30,
    )
    state = AlertState(redis_client)
    http_client = httpx.AsyncClient(timeout=5.0)

    app = make_app(cfg, metrics, state, log)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, cfg.listen_host, cfg.listen_port)
    await site.start()
    log.info("server.listening", host=cfg.listen_host, port=cfg.listen_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    eval_task = asyncio.create_task(
        _eval_loop(cfg, http_client, state, metrics, log, stop), name="eval_loop"
    )

    await stop.wait()
    log.info("shutdown.begin")
    eval_task.cancel()
    with __import__("contextlib").suppress(Exception):
        await eval_task
    await runner.cleanup()
    await http_client.aclose()
    await state.close()
    log.info("shutdown.complete")
    return 0


async def _eval_loop(
    cfg: Config, http: httpx.AsyncClient, state: AlertState, metrics, log, stop: asyncio.Event
) -> None:
    """Pull snapshot -> evaluate rules -> persist + publish."""
    log.info("eval.loop.started", interval_s=cfg.eval_interval_seconds)
    consecutive_fail = 0
    while not stop.is_set():
        snapshot = await _fetch_snapshot(cfg, http, log, metrics)
        if snapshot is None:
            consecutive_fail += 1
            if consecutive_fail == 3:
                log.warning("snapshot.unavailable", consecutive_fail=consecutive_fail)
        else:
            consecutive_fail = 0
            fired = evaluate_all(snapshot)
            for alert in fired:
                await _emit(alert, cfg, state, metrics, log)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.eval_interval_seconds)
        except asyncio.TimeoutError:
            continue
    log.info("eval.loop.stopped")


async def _fetch_snapshot(cfg: Config, http: httpx.AsyncClient, log, metrics) -> dict | None:
    try:
        r = await http.get(f"{cfg.metrics_url}/api/snapshot")
        if r.status_code != 200:
            metrics.redis_errors.labels("snapshot_http").inc()
            return None
        return r.json()
    except Exception:
        metrics.redis_errors.labels("snapshot_exception").inc()
        return None


async def _emit(
    alert: Alert, cfg: Config, state: AlertState, metrics, log
) -> None:
    """Apply cooldown gate + publish + persist."""
    doc = {
        "alertname": alert.alertname,
        "severity": alert.severity,
        "domain": alert.domain,
        "labels": alert.labels,
        "annotations": {"summary": alert.summary, **alert.annotations},
        "summary": alert.summary,
        "startsAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    metrics.received.labels(alert.severity, "evaluator").inc()
    fp = fingerprint(doc)
    doc["fp"] = fp

    try:
        if await state.is_in_cooldown(fp):
            metrics.deduped.labels(alert.severity).inc()
            return
    except Exception:
        metrics.redis_errors.labels("is_in_cooldown").inc()
        # fail-open: still attempt to mark + publish

    cooldown = cooldown_seconds(alert.alertname, alert.severity, cfg.cooldown_for(alert.severity))
    doc["cooldown_seconds"] = cooldown
    doc["event"] = "alert.firing"

    try:
        await state.mark_active(fp, doc, cooldown)
    except Exception:
        metrics.redis_errors.labels("mark_active").inc()

    try:
        await state.publish(cfg.pubsub_channel, doc)
    except Exception:
        metrics.redis_errors.labels("publish").inc()

    metrics.emitted.labels(alert.severity, alert.domain).inc()


def main() -> int:
    if uvloop is not None:
        uvloop.install()
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
