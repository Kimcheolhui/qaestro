"""OpenAI-compatible Agent Runtime provider boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from src.runtime.agent.azure_openai import AzureOpenAIAgentRunner, AzureOpenAIChatClient, AzureOpenAIHTTPClient
from src.runtime.agent.fake import FakeAgentRunner
from src.runtime.agent.health import AgentRuntimeHealthStatus, check_agent_runtime_health
from src.runtime.agent.types import AgentRunInput, AgentRunner, AgentRunResult, AgentRunStatus, AgentSessionHandle
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider
from src.shared.redaction import redact_text


@dataclass(frozen=True)
class OpenAICompatibleClientResponse:
    """Provider-adapter response normalized before entering qaestro contracts."""

    output_text: str
    error: str = ""


class OpenAICompatibleChatClient(Protocol):
    """Minimal mocked/live client seam for OpenAI-compatible chat completion."""

    def complete(self, request: dict[str, object]) -> OpenAICompatibleClientResponse: ...


class OpenAICompatibleAgentRunner(AgentRunner):
    """Provider-neutral runner backed by an OpenAI-compatible client seam.

    This adapter intentionally accepts a narrow client protocol instead of a
    concrete SDK object. Tests can inject a fake client without credentials, and
    future live clients can translate this request shape to a specific SDK/API.
    """

    def __init__(self, *, config: AgentRuntimeConfig, client: OpenAICompatibleChatClient, credential: str) -> None:
        self._config = config
        self._client = client
        self._credential = credential

    def start_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        return handle

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        try:
            response = self._client.complete(self._request_for(session=session, run_input=run_input))
        except Exception as exc:
            return AgentRunResult(
                session=session,
                stage=run_input.stage,
                status=AgentRunStatus.FAILED,
                error=_redact_secret(str(exc), self._credential),
                allowed_tool_names=run_input.allowed_tool_names,
            )
        if response.error:
            return AgentRunResult(
                session=session,
                stage=run_input.stage,
                status=AgentRunStatus.FAILED,
                error=_redact_secret(response.error, self._credential),
                allowed_tool_names=run_input.allowed_tool_names,
            )
        return AgentRunResult(
            session=session,
            stage=run_input.stage,
            status=AgentRunStatus.SUCCEEDED,
            output_text=response.output_text,
            allowed_tool_names=run_input.allowed_tool_names,
        )

    def close_session(self, handle: AgentSessionHandle, *, reason: str) -> None:
        _ = (handle, reason)

    def _request_for(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> dict[str, object]:
        _ = session
        return {
            "base_url": self._config.base_url,
            "model": self._config.model,
            "prompt": run_input.prompt,
            "stage": run_input.stage.value,
            "correlation_id": run_input.correlation_id,
            "timeout_seconds": self._config.timeout_seconds
            if run_input.timeout_seconds is None
            else run_input.timeout_seconds,
            "max_turns": self._config.max_turns if run_input.max_turns is None else run_input.max_turns,
            "max_tool_calls": self._config.max_tool_calls
            if run_input.max_tool_calls is None
            else run_input.max_tool_calls,
            "temperature": self._config.temperature,
            "tool_names": run_input.allowed_tool_names,
            "credential_present": bool(self._credential),
        }


class UnsupportedAgentRuntimeProviderError(ValueError):
    """Raised when runner construction rejects provider config."""


def build_agent_runner(
    config: AgentRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    openai_compatible_client: OpenAICompatibleChatClient | None = None,
    azure_openai_client: AzureOpenAIChatClient | None = None,
) -> AgentRunner:
    """Build a provider-neutral runner from Agent Runtime configuration."""

    if config.provider is AgentRuntimeProvider.DISABLED:
        return FakeAgentRunner(response="agent runtime disabled; validation probe selection skipped")

    env = os.environ if environ is None else environ
    health = check_agent_runtime_health(config, environ=env)
    if health.status is AgentRuntimeHealthStatus.UNSUPPORTED:
        raise UnsupportedAgentRuntimeProviderError("; ".join(health.actionable_errors))

    if config.provider is AgentRuntimeProvider.OPENAI_COMPATIBLE:
        if openai_compatible_client is None:
            raise UnsupportedAgentRuntimeProviderError(
                "OpenAI-compatible runner requires an injected client until a live adapter is configured."
            )
        return OpenAICompatibleAgentRunner(
            config=config,
            client=openai_compatible_client,
            credential=env.get(config.credential_env_var, ""),
        )

    if config.provider is AgentRuntimeProvider.AZURE_OPENAI:
        credential = env.get(config.credential_env_var, "")
        return AzureOpenAIAgentRunner(
            config=config,
            client=azure_openai_client or AzureOpenAIHTTPClient(credential=credential),
            credential=credential,
        )

    raise UnsupportedAgentRuntimeProviderError(
        f"Agent Runtime provider {config.provider.value!r} is not implemented yet."
    )


def _redact_secret(value: str, secret: str) -> str:
    return redact_text(value, explicit_secrets=(secret,), redact_urls=True)
