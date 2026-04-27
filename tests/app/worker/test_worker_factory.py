"""Tests for worker factory wiring."""

from __future__ import annotations

from pathlib import Path

from src.app.worker.factory import build_worker
from src.app.worker.runner import NoopOutputPoster
from src.runtime.orchestrator import EventOrchestrator, ToolRuntimePRCommentPoster, ToolRuntimePRContextProvider
from src.shared.config import AppConfig


def _orchestrator(worker: object) -> object:
    return worker._orchestrator  # type: ignore[attr-defined]


def _output_poster(worker: object) -> object:
    return worker._output_poster  # type: ignore[attr-defined]


def test_build_worker_uses_noop_output_poster_for_memory_queue() -> None:
    worker = build_worker(AppConfig(queue_backend="memory"))

    assert isinstance(_output_poster(worker), NoopOutputPoster)


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


def test_build_worker_wires_github_tool_runtime_for_durable_queue(tmp_path: Path) -> None:
    key_path = tmp_path / "app.pem"
    key_path.write_text("private-key", encoding="utf-8")
    cfg = AppConfig(
        queue_backend="redis-streams",
        github_app_id=1,
        github_app_installation_id=2,
        github_app_private_key_path=str(key_path),
    )

    worker = build_worker(cfg)

    orchestrator = _orchestrator(worker)
    assert isinstance(orchestrator, EventOrchestrator)
    pr_orchestrator = orchestrator._pr_orchestrator
    assert isinstance(pr_orchestrator._context_provider, ToolRuntimePRContextProvider)
    assert isinstance(_output_poster(worker), ToolRuntimePRCommentPoster)
