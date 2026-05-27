"""Uvicorn entrypoint."""

from __future__ import annotations

import sys

import uvicorn

try:
    import uvloop
except ImportError:
    uvloop = None  # type: ignore[assignment]

from .config import Config


def main() -> int:
    cfg = Config()
    cfg.validate()
    if uvloop is not None:
        uvloop.install()
    uvicorn.run(
        "btc_health_api.app:create_app",
        factory=True,
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_level=cfg.log_level.lower(),
        access_log=False,
        proxy_headers=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
