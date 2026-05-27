"""
Structured JSON logging. Promtail's pipeline expects:
  { ts, level, service, event, correlation_id, msg, ... }

Free-form text goes in `msg`; stable machine-readable keys go in `event`.
"""

from __future__ import annotations

import logging

import structlog

from .config import Config


def configure_logging(cfg: Config) -> structlog.stdlib.BoundLogger:
    """Configure structlog + stdlib logging to emit JSON.

    Returns a bound logger pre-populated with service identity.
    """
    level = getattr(logging, cfg.log_level, logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)
    # silence noisy underlying libs
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Use stdlib LoggerFactory so:
    #   * level filtering goes through logging.basicConfig (above)
    #   * BoundLogger.info(msg, **kw) accepts `event=` as a regular kwarg
    #     (make_filtering_bound_logger would collide with `event` positional)
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

    return structlog.get_logger().bind(
        service=cfg.service_name,
        service_version=cfg.service_version,
    )
