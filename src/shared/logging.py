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
        # Merge extra fields attached via ``logger.info("msg", extra={...})``.
        # Keep the whitelist explicit so logs stay predictable and don't leak
        # arbitrary objects.
        for key in (
            "attempts",
            "correlation_id",
            "delivery_id",
            "error",
            "event_type",
            "job_type",
            "module_name",
        ):
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
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    _VALID_FORMATS = ("json", "text")
    if fmt not in _VALID_FORMATS:
        msg = f"Unsupported log format {fmt!r}, expected one of {_VALID_FORMATS}"
        raise ValueError(msg)

    handler = logging.StreamHandler(stream or sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_TextFormatter())

    root.addHandler(handler)
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        msg = f"Invalid log level {level!r}"
        raise ValueError(msg)
    root.setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger scoped under ``qaestro.``."""
    return logging.getLogger(f"qaestro.{name}")
