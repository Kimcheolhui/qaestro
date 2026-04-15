"""Tests for src.shared — config, logging, tracing."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

from src.shared.config import AppConfig, load_config
from src.shared.logging import get_logger, setup_logging
from src.shared.tracing import (
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)


class TestAppConfig:
    """AppConfig loading from env vars."""

    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.debug is False
        assert cfg.log_format == "json"

    def test_env_override(self) -> None:
        env = {
            "DEVCLAW_DEBUG": "true",
            "DEVCLAW_LOG_LEVEL": "DEBUG",
            "DEVCLAW_LOG_FORMAT": "text",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.debug is True
        assert cfg.log_level == "DEBUG"
        assert cfg.log_format == "text"

    def test_frozen(self) -> None:
        cfg = load_config()
        try:
            cfg.debug = True  # type: ignore[misc]
            raise AssertionError("should be frozen")
        except AttributeError:
            pass


class TestLogging:
    """Structured logging setup."""

    def test_get_logger_returns_logger(self) -> None:
        log = get_logger("test.module")
        assert isinstance(log, logging.Logger)
        assert log.name == "devclaw.test.module"

    def test_setup_logging_json(self) -> None:
        setup_logging(level="WARNING", fmt="json")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_setup_logging_text(self) -> None:
        setup_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestTracing:
    """Correlation-id propagation."""

    def test_new_and_get(self) -> None:
        cid = new_correlation_id()
        assert len(cid) == 16
        assert get_correlation_id() == cid

    def test_set_and_get(self) -> None:
        set_correlation_id("abc123")
        assert get_correlation_id() == "abc123"
