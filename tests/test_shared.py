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
            "QAESTRO_DEBUG": "true",
            "QAESTRO_LOG_LEVEL": "DEBUG",
            "QAESTRO_LOG_FORMAT": "text",
            "QAESTRO_QUEUE_BACKEND": "redis-streams",
            "QAESTRO_REDIS_URL": "redis://redis:6379/1",
            "QAESTRO_REDIS_STREAM": "qaestro:test:jobs",
            "QAESTRO_REDIS_CONSUMER_GROUP": "qaestro-test-workers",
            "QAESTRO_REDIS_CONSUMER": "worker-a",
            "QAESTRO_REDIS_READ_BLOCK_MS": "2500",
            "QAESTRO_REDIS_CLAIM_IDLE_MS": "60000",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.debug is True
        assert cfg.log_level == "DEBUG"
        assert cfg.log_format == "text"
        assert cfg.queue_backend == "redis-streams"
        assert cfg.redis_url == "redis://redis:6379/1"
        assert cfg.redis_stream == "qaestro:test:jobs"
        assert cfg.redis_consumer_group == "qaestro-test-workers"
        assert cfg.redis_consumer == "worker-a"
        assert cfg.redis_read_block_ms == 2500
        assert cfg.redis_claim_idle_ms == 60000

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
        assert log.name == "qaestro.test.module"

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
