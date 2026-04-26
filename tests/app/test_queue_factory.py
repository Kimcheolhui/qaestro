"""Tests for queue factory wiring."""

from __future__ import annotations

from typing import Any

import pytest

from src.app.jobs import InMemoryJobQueue
from src.app.queue_factory import build_job_queue
from src.shared.config import AppConfig


def test_build_job_queue_defaults_to_in_memory() -> None:
    queue = build_job_queue(AppConfig())

    assert isinstance(queue, InMemoryJobQueue)


def test_build_job_queue_uses_redis_stream_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeRedisStreamsQueue:
        @classmethod
        def from_url(cls, redis_url: str, **kwargs: Any) -> FakeRedisStreamsQueue:
            calls.append({"redis_url": redis_url, **kwargs})
            return cls()

    monkeypatch.setattr("src.app.queue_factory.RedisStreamsJobQueue", FakeRedisStreamsQueue)
    cfg = AppConfig(
        queue_backend="redis-streams",
        redis_url="redis://redis:6379/1",
        redis_stream="qaestro:test:jobs",
        redis_consumer_group="qaestro-test-workers",
        redis_consumer="worker-a",
        redis_read_block_ms=2500,
        redis_claim_idle_ms=60000,
    )

    queue = build_job_queue(cfg)

    assert isinstance(queue, FakeRedisStreamsQueue)
    assert calls == [
        {
            "redis_url": "redis://redis:6379/1",
            "stream": "qaestro:test:jobs",
            "group": "qaestro-test-workers",
            "consumer": "worker-a",
            "read_block_ms": 2500,
            "claim_idle_ms": 60000,
        }
    ]


def test_build_job_queue_rejects_unknown_backend() -> None:
    cfg = AppConfig(queue_backend="unknown")

    with pytest.raises(ValueError, match="Unsupported queue backend"):
        build_job_queue(cfg)
