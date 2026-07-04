from __future__ import annotations

import json
import logging
import sys
from types import TracebackType
from typing import TextIO

from backend.config.settings import PlatformSettings


class StructuredJsonFormatter(logging.Formatter):
    """JSON log formatter supporting LOG-001 structured diagnostics."""

    def __init__(self, app_name: str, environment: str) -> None:
        super().__init__()
        self._app_name = app_name
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "app": self._app_name,
            "environment": self._environment,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(
                cast_exception_info(record.exc_info),
            )

        return json.dumps(payload, sort_keys=True)


def cast_exception_info(
    exc_info: (
        tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None]
    ),
) -> tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]:
    return exc_info


def configure_logging(settings: PlatformSettings, stream: TextIO | None = None) -> None:
    """Configure process logging from validated settings for LOG-001."""

    log_level = logging.getLevelName(settings.logging.level.upper())
    if not isinstance(log_level, int):
        raise ValueError(f"Unsupported log level: {settings.logging.level}")

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        StructuredJsonFormatter(
            app_name=settings.app.name,
            environment=settings.app.environment,
        ),
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
