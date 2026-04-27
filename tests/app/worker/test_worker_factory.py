"""Tests for worker factory wiring."""

from __future__ import annotations

from pathlib import Path

from src.app.worker.factory import build_worker
from src.app.worker.github import GitHubCommentPoster
from src.app.worker.runner import NoopCommentPoster
from src.runtime.orchestrator import EventOrchestrator
from src.shared.config import AppConfig


def _orchestrator(worker: object) -> object:
    return worker._orchestrator  # type: ignore[attr-defined]


def _comment_poster(worker: object) -> object:
    return worker._comment_poster  # type: ignore[attr-defined]


def test_build_worker_uses_noop_poster_for_memory_queue() -> None:
    worker = build_worker(AppConfig(queue_backend="memory"))

    assert isinstance(_comment_poster(worker), NoopCommentPoster)


def test_build_worker_rejects_durable_queue_without_github_app_id() -> None:
    cfg = AppConfig(queue_backend="redis-streams")

    try:
        build_worker(cfg)
        raise AssertionError("expected missing GitHub App config to fail")
    except ValueError as exc:
        assert "QAESTRO_GITHUB_APP_ID" in str(exc)


def test_build_worker_rejects_durable_queue_without_installation_id(tmp_path: Path) -> None:
    key_path = tmp_path / "app.pem"
    key_path.write_text("private-key", encoding="utf-8")
    cfg = AppConfig(
        queue_backend="redis-streams",
        github_app_id=1,
        github_app_private_key_path=str(key_path),
    )

    try:
        build_worker(cfg)
        raise AssertionError("expected missing installation id to fail")
    except ValueError as exc:
        assert "QAESTRO_GITHUB_APP_INSTALLATION_ID" in str(exc)


def test_build_worker_rejects_durable_queue_without_private_key_path() -> None:
    cfg = AppConfig(
        queue_backend="redis-streams",
        github_app_id=1,
        github_app_installation_id=2,
    )

    try:
        build_worker(cfg)
        raise AssertionError("expected missing private key path to fail")
    except ValueError as exc:
        assert "QAESTRO_GITHUB_APP_PRIVATE_KEY_PATH" in str(exc)


def test_build_worker_wires_github_poster_for_durable_queue(tmp_path: Path) -> None:
    key_path = tmp_path / "app.pem"
    key_path.write_text("private-key", encoding="utf-8")
    cfg = AppConfig(
        queue_backend="redis-streams",
        github_app_id=1,
        github_app_installation_id=2,
        github_app_private_key_path=str(key_path),
    )

    worker = build_worker(cfg)

    assert isinstance(_comment_poster(worker), GitHubCommentPoster)
    assert isinstance(_orchestrator(worker), EventOrchestrator)
