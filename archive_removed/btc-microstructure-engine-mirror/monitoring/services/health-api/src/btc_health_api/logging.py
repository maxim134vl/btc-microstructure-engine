"""Structured JSON logging."""

from __future__ import annotations

import logging

import structlog

from .config import Config


def configure_logging(cfg: Config) -> structlog.stdlib.BoundLogger:
    level = getattr(logging, cfg.log_level, logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.contextvars.merge_contextvars,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger().bind(service=cfg.service_name, service_version=cfg.service_version)
