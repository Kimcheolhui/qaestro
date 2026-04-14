"""Structured JSON logger.

Provides a lightweight structured logging setup using stdlib ``logging``.
Outputs JSON lines in production (``json`` format) or human-readable text
in development (``text`` format).  No external dependencies.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        # Merge extra fields attached via ``logger.info("msg", extra={...})``
        for key in ("correlation_id", "module_name", "event_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    FMT = "%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt="%H:%M:%S")


def setup_logging(
    *,
    level: str = "INFO",
    fmt: str = "json",
    stream: Any = None,
) -> None:
    """Configure the root logger for the application.

    Args:
        level: Logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
        fmt: ``"json"`` for structured output, ``"text"`` for dev-friendly.
        stream: Output stream; defaults to ``sys.stderr``.
    """
    root = logging.getLogger()

    # Remove existing handlers to allow re-configuration
    root.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_TextFormatter())

    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Return a named logger scoped under ``devclaw.``."""
    return logging.getLogger(f"devclaw.{name}")
