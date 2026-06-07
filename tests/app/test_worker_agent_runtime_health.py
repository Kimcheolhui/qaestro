"""Tests for Agent Runtime health check wiring at worker bootstrap."""

from __future__ import annotations

from src.app.worker import AgentRuntimeUnavailableError, check_worker_agent_runtime_health
from src.runtime.agent import AgentRuntimeHealthStatus
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider, AppConfig


def test_worker_agent_runtime_health_allows_disabled_runtime_for_local_development() -> None:
    result = check_worker_agent_runtime_health(AppConfig())

    assert result.status is AgentRuntimeHealthStatus.DISABLED


def test_worker_agent_runtime_health_fails_closed_for_unsupported_config() -> None:
    cfg = AppConfig(
        agent_runtime=AgentRuntimeConfig(
            provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
            model="review-model",
            base_url="https://llm.example.test/v1",
            credential_env_var="QAESTRO_AGENT_API_KEY",
            supports_tool_calling=False,
            supports_structured_output=True,
            context_window_tokens=64_000,
        )
    )

    try:
        check_worker_agent_runtime_health(cfg, environ={"QAESTRO_AGENT_API_KEY": "opaque-runtime-credential"})
    except AgentRuntimeUnavailableError as exc:
        message = str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("unsupported Agent Runtime config should fail closed")

    assert "tool calling is required" in message
    assert "opaque-runtime-credential" not in message
