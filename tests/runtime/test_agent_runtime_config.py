"""Tests for Agent Runtime configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider, AppConfig, load_config


class TestAgentRuntimeConfig:
    """Agent Runtime settings are explicit and secret-safe."""

    def test_defaults_keep_agent_runtime_disabled_for_local_development(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()

        assert isinstance(cfg.agent_runtime, AgentRuntimeConfig)
        assert cfg.agent_runtime.provider is AgentRuntimeProvider.DISABLED
        assert cfg.agent_runtime.model == ""
        assert cfg.agent_runtime.credential_env_var == ""
        assert cfg.agent_runtime.timeout_seconds == 60.0
        assert cfg.agent_runtime.max_turns == 8
        assert cfg.agent_runtime.max_tool_calls == 16
        assert cfg.agent_runtime.temperature == 0.0

    def test_load_config_reads_qaestro_agent_environment_variables(self) -> None:
        env = {
            "QAESTRO_AGENT_PROVIDER": "azure-openai",
            "QAESTRO_AGENT_MODEL": "gpt-4.1",
            "QAESTRO_AGENT_DEPLOYMENT": "qaestro-reviewer",
            "QAESTRO_AGENT_ENDPOINT": "https://example.openai.azure.com/",
            "QAESTRO_AGENT_BASE_URL": "https://api.example.com/v1",
            "QAESTRO_AGENT_API_VERSION": "2025-01-01-preview",
            "QAESTRO_AGENT_CREDENTIAL_ENV_VAR": "QAESTRO_AGENT_API_KEY",
            "QAESTRO_AGENT_TIMEOUT_SECONDS": "90.5",
            "QAESTRO_AGENT_MAX_TURNS": "12",
            "QAESTRO_AGENT_MAX_TOOL_CALLS": "24",
            "QAESTRO_AGENT_TEMPERATURE": "0.2",
            "QAESTRO_AGENT_SUPPORTS_TOOL_CALLING": "true",
            "QAESTRO_AGENT_SUPPORTS_STRUCTURED_OUTPUT": "yes",
            "QAESTRO_AGENT_CONTEXT_WINDOW_TOKENS": "64000",
        }

        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()

        assert cfg.agent_runtime == AgentRuntimeConfig(
            provider=AgentRuntimeProvider.AZURE_OPENAI,
            model="gpt-4.1",
            deployment="qaestro-reviewer",
            endpoint="https://example.openai.azure.com/",
            base_url="https://api.example.com/v1",
            api_version="2025-01-01-preview",
            credential_env_var="QAESTRO_AGENT_API_KEY",
            timeout_seconds=90.5,
            max_turns=12,
            max_tool_calls=24,
            temperature=0.2,
            supports_tool_calling=True,
            supports_structured_output=True,
            context_window_tokens=64_000,
        )

    def test_agent_runtime_config_repr_redacts_credential_reference(self) -> None:
        config = AgentRuntimeConfig(
            provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
            model="review-model",
            credential_env_var="SECRET_ENV_NAME",
        )

        rendered = repr(config)

        assert "SECRET_ENV_NAME" not in rendered
        assert "credential_env_var=<redacted>" in rendered

    def test_app_config_repr_does_not_leak_agent_credential_reference(self) -> None:
        cfg = AppConfig(
            agent_runtime=AgentRuntimeConfig(
                provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
                model="review-model",
                credential_env_var="SECRET_ENV_NAME",
            )
        )

        assert "SECRET_ENV_NAME" not in repr(cfg)
