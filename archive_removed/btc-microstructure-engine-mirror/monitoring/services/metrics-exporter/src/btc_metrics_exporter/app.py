"""
Entrypoint. Wires together config -> logging -> metrics -> collectors -> server,
runs the scan loop and HTTP server concurrently, and handles graceful shutdown.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Sequence

from aiohttp import web

try:
    import uvloop
except ImportError:
    uvloop = None  # type: ignore[assignment]

from .collectors import (
    Collector,
    FeatureHealthCollector,
    ParquetScannerCollector,
    RegimeDistributionCollector,
    RuntimeProbeCollector,
)
from .config import Config
from .logging import configure_logging
from .registry import build_metrics
from .server import make_app


async def scan_loop(
    cfg: Config,
    collectors: Sequence[Collector],
    state: dict,
    stop: asyncio.Event,
) -> None:
    """Run every collector once per scan_interval. State is mutated for /readyz."""
    log = collectors[0].log.bind(loop="scan")  # any collector's logger has service bound
    log.info("scan.loop.started", interval=cfg.scan_interval_seconds)
    while not stop.is_set():
        # collectors are independent — run concurrently
        await asyncio.gather(*(c.safe_collect() for c in collectors))
        state["scans_completed"] = state.get("scans_completed", 0) + 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.scan_interval_seconds)
        except asyncio.TimeoutError:
            continue
    log.info("scan.loop.stopped")


async def main_async() -> int:
    cfg = Config()
    cfg.validate()
    log = configure_logging(cfg)
    log.info(
        "startup",
        port=cfg.listen_port,
        data_dir=str(cfg.data_dir),
        scan_interval=cfg.scan_interval_seconds,
    )

    metrics = build_metrics()
    state: dict = {"scans_completed": 0, "history": {}}
    collectors: list[Collector] = [
        ParquetScannerCollector(cfg, metrics, log, state),
        FeatureHealthCollector(cfg, metrics, log, state),
        RegimeDistributionCollector(cfg, metrics, log, state),
        RuntimeProbeCollector(cfg, metrics, log, state),
    ]
    stop = asyncio.Event()

    # signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # not supported on win32; ignore
            pass

    app = make_app(metrics, state, cfg.data_dir)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, cfg.listen_host, cfg.listen_port)
    await site.start()
    log.info("server.listening", host=cfg.listen_host, port=cfg.listen_port)

    scan_task = asyncio.create_task(scan_loop(cfg, collectors, state, stop), name="scan_loop")

    await stop.wait()
    log.info("shutdown.begin")

    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        pass
    await runner.cleanup()
    log.info("shutdown.complete")
    return 0


def main() -> int:
    if uvloop is not None:
        uvloop.install()
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
