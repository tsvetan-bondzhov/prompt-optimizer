"""Logging configuration for the application.

Call :func:`configure_logging` once during application startup (e.g. in the
FastAPI lifespan handler) to initialize console logging.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

from app.config import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def configure_logging(level: str | None = None) -> None:
    """Initialize structured console logging.

    Args:
        level: Optional log level override. Defaults to ``settings.LOG_LEVEL``.
    """

    global _configured

    resolved_level = (level or get_settings().LOG_LEVEL).upper()

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": _LOG_FORMAT,
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": resolved_level,
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn": {"level": resolved_level},
                "uvicorn.error": {"level": resolved_level},
                "uvicorn.access": {"level": resolved_level},
            },
        }
    )

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring logging on first use if needed."""

    if not _configured:
        configure_logging()
    return logging.getLogger(name)
