"""Tests for Agent Runtime capability policy and health checks."""

from __future__ import annotations

from src.runtime.agent import AgentRuntimeHealthStatus, check_agent_runtime_health
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider


def test_disabled_agent_runtime_health_is_disabled_without_credentials() -> None:
    result = check_agent_runtime_health(AgentRuntimeConfig())

    assert result.status is AgentRuntimeHealthStatus.DISABLED
    assert result.provider is AgentRuntimeProvider.DISABLED
    assert result.actionable_errors == ()
    assert result.warnings == ("Agent Runtime is disabled; runtime validation will not call an LLM provider.",)


def test_openai_compatible_runtime_requires_tool_calling_and_structured_output() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
        model="small-chat-model",
        base_url="https://llm.example.test/v1",
        credential_env_var="QAESTRO_AGENT_API_KEY",
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window_tokens=16_000,
    )

    result = check_agent_runtime_health(config, environ={"QAESTRO_AGENT_API_KEY": "super-secret-token"})

    assert result.status is AgentRuntimeHealthStatus.UNSUPPORTED
    assert result.ok is False
    assert "tool calling is required" in result.actionable_errors
    assert "structured output or schema-constrained responses are required" in result.actionable_errors
    assert "super-secret-token" not in repr(result)
    assert "super-secret-token" not in str(result.actionable_errors)


def test_azure_openai_runtime_reports_missing_endpoint_deployment_api_version_and_credential() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.AZURE_OPENAI,
        credential_env_var="QAESTRO_AZURE_OPENAI_KEY",
    )

    result = check_agent_runtime_health(config, environ={})

    assert result.status is AgentRuntimeHealthStatus.UNSUPPORTED
    assert result.actionable_errors == (
        "Azure OpenAI endpoint is required for QAESTRO_AGENT_ENDPOINT.",
        "Azure OpenAI deployment is required for QAESTRO_AGENT_DEPLOYMENT.",
        "Azure OpenAI API version is required for QAESTRO_AGENT_API_VERSION.",
        "Credential environment variable QAESTRO_AZURE_OPENAI_KEY is not set.",
    )


def test_enabled_runtime_requires_declared_context_window() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
        model="review-model",
        base_url="https://llm.example.test/v1",
        credential_env_var="QAESTRO_AGENT_API_KEY",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=0,
    )

    result = check_agent_runtime_health(config, environ={"QAESTRO_AGENT_API_KEY": "super-secret-token"})

    assert result.status is AgentRuntimeHealthStatus.UNSUPPORTED
    assert result.ok is False
    assert result.actionable_errors == ("context window token capacity is required for QAESTRO_AGENT_CONTEXT_WINDOW_TOKENS.",)


def test_supported_runtime_can_warn_when_live_smoke_is_not_enabled() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
        model="review-model",
        base_url="https://llm.example.test/v1",
        credential_env_var="QAESTRO_AGENT_API_KEY",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=64_000,
    )

    result = check_agent_runtime_health(config, environ={"QAESTRO_AGENT_API_KEY": "super-secret-token"})

    assert result.status is AgentRuntimeHealthStatus.SUPPORTED
    assert result.ok is True
    assert result.actionable_errors == ()
    assert result.warnings == ("Live provider smoke check not executed; set opt_in_live_smoke=True to probe provider connectivity.",)
    assert "super-secret-token" not in repr(result)


def test_capability_policy_marks_small_context_window_as_degraded() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
        model="review-model",
        base_url="https://llm.example.test/v1",
        credential_env_var="QAESTRO_AGENT_API_KEY",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=8_000,
    )

    result = check_agent_runtime_health(config, environ={"QAESTRO_AGENT_API_KEY": "super-secret-token"})

    assert result.status is AgentRuntimeHealthStatus.DEGRADED
    assert result.ok is True
    assert result.actionable_errors == ()
    assert result.warnings[0] == "Configured context window 8000 tokens is below the recommended 32000 tokens."
