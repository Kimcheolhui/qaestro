"""Tests for worker entrypoint helpers."""

from __future__ import annotations

import pytest

from src.app.worker.entrypoint import default_redis_consumer_name


def test_default_redis_consumer_name_is_process_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.app.worker.entrypoint.socket.gethostname", lambda: "worker-host")
    monkeypatch.setattr("src.app.worker.entrypoint.os.getpid", lambda: 1234)

    assert default_redis_consumer_name() == "worker-host-1234"
