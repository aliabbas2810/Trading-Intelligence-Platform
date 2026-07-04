from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from backend.config import load_settings
from backend.core import configure_logging, get_logger


def test_configure_logging_writes_structured_json() -> None:
    """Covers LOG-001 and TEST-001."""

    settings = load_settings()
    stream = io.StringIO()

    configure_logging(settings, stream=stream)
    get_logger("backend.tests").info("foundation ready")

    payload = json.loads(stream.getvalue())

    assert payload["app"] == "trading-intelligence-platform"
    assert payload["environment"] == "local"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "backend.tests"
    assert payload["message"] == "foundation ready"
    assert isinstance(payload["timestamp"], str)


def test_configure_logging_rejects_invalid_log_level() -> None:
    """Covers LOG-001 and TEST-001."""

    settings = load_settings()
    invalid_settings = settings.model_copy(
        update={"logging": settings.logging.model_copy(update={"level": "LOUD"})},
    )

    with pytest.raises(ValueError, match="Unsupported log level"):
        configure_logging(invalid_settings)

    logging.getLogger().handlers.clear()


def test_structured_logging_includes_exception_details() -> None:
    """Covers LOG-001 and TEST-001."""

    settings = load_settings()
    stream = io.StringIO()

    configure_logging(settings, stream=stream)
    logger = get_logger("backend.tests")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("failure path")

    payload: dict[str, Any] = json.loads(stream.getvalue())

    assert payload["message"] == "failure path"
    assert "RuntimeError: boom" in payload["exception"]
