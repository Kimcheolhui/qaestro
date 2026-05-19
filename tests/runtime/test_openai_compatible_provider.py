"""Tests for OpenAI-compatible Agent Runtime provider boundary."""

from __future__ import annotations

from src.runtime.agent import (
    AgentRunInput,
    AgentRunStatus,
    AgentSessionHandle,
    AgentSessionScope,
    FakeAgentRunner,
    OpenAICompatibleAgentRunner,
    OpenAICompatibleChatClient,
    OpenAICompatibleClientResponse,
    build_agent_runner,
)
from src.runtime.stages import WorkflowStage
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider


class RecordingOpenAICompatibleClient(OpenAICompatibleChatClient):
    def __init__(self, response: OpenAICompatibleClientResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, request: dict[str, object]) -> OpenAICompatibleClientResponse:
        self.calls.append(request)
        return self.response


class FailingOpenAICompatibleClient(OpenAICompatibleChatClient):
    def complete(self, request: dict[str, object]) -> OpenAICompatibleClientResponse:
        _ = request
        raise TimeoutError("provider timed out with credential super-secret-token")


def _supported_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        provider=AgentRuntimeProvider.OPENAI_COMPATIBLE,
        model="review-model",
        base_url="https://llm.example.test/v1",
        credential_env_var="QAESTRO_AGENT_API_KEY",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=64_000,
        timeout_seconds=45.0,
        max_turns=4,
        max_tool_calls=6,
        temperature=0.1,
    )


def _session() -> AgentSessionHandle:
    return AgentSessionHandle(
        session_id="session-1",
        scope=AgentSessionScope.WORKFLOW,
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=76,
        head_sha="abc123",
        trigger="manual",
        correlation_id="corr-1",
    )


def test_openai_compatible_runner_builds_provider_neutral_request_without_secret_value() -> None:
    client = RecordingOpenAICompatibleClient(OpenAICompatibleClientResponse(output_text="analysis ok"))
    runner = OpenAICompatibleAgentRunner(
        config=_supported_config(),
        client=client,
        credential="super-secret-token",
    )
    session = runner.start_session(_session())

    result = runner.run(
        session=session,
        run_input=AgentRunInput(
            stage=WorkflowStage.VALIDATOR,
            prompt="Validate the PR",
            correlation_id="corr-1",
            max_turns=2,
            max_tool_calls=3,
            timeout_seconds=30.0,
        ),
    )

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.output_text == "analysis ok"
    assert result.stage is WorkflowStage.VALIDATOR
    assert client.calls == [
        {
            "base_url": "https://llm.example.test/v1",
            "model": "review-model",
            "prompt": "Validate the PR",
            "stage": "validator",
            "correlation_id": "corr-1",
            "timeout_seconds": 30.0,
            "max_turns": 2,
            "max_tool_calls": 3,
            "temperature": 0.1,
            "tool_names": (),
            "credential_present": True,
        }
    ]
    assert "super-secret-token" not in repr(client.calls[0])


def test_openai_compatible_runner_normalizes_client_errors_without_secret_value() -> None:
    client = RecordingOpenAICompatibleClient(
        OpenAICompatibleClientResponse(output_text="", error="provider unavailable: super-secret-token")
    )
    runner = OpenAICompatibleAgentRunner(
        config=_supported_config(),
        client=client,
        credential="super-secret-token",
    )

    result = runner.run(
        session=_session(),
        run_input=AgentRunInput(stage=WorkflowStage.VALIDATOR, prompt="Validate", correlation_id="corr-1"),
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error == "provider unavailable: <redacted>"


def test_openai_compatible_runner_preserves_explicit_zero_budgets() -> None:
    client = RecordingOpenAICompatibleClient(OpenAICompatibleClientResponse(output_text="analysis ok"))
    runner = OpenAICompatibleAgentRunner(
        config=_supported_config(),
        client=client,
        credential="super-secret-token",
    )

    result = runner.run(
        session=_session(),
        run_input=AgentRunInput(
            stage=WorkflowStage.VALIDATOR,
            prompt="Validate without tools",
            correlation_id="corr-1",
            timeout_seconds=0.0,
            max_turns=0,
            max_tool_calls=0,
        ),
    )

    assert result.status is AgentRunStatus.SUCCEEDED
    assert client.calls[0]["timeout_seconds"] == 0.0
    assert client.calls[0]["max_turns"] == 0
    assert client.calls[0]["max_tool_calls"] == 0


def test_openai_compatible_runner_normalizes_client_exceptions_without_secret_value() -> None:
    runner = OpenAICompatibleAgentRunner(
        config=_supported_config(),
        client=FailingOpenAICompatibleClient(),
        credential="super-secret-token",
    )

    result = runner.run(
        session=_session(),
        run_input=AgentRunInput(stage=WorkflowStage.VALIDATOR, prompt="Validate", correlation_id="corr-1"),
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error == "provider timed out with credential <redacted>"


def test_agent_runner_factory_builds_fake_runner_for_disabled_runtime() -> None:
    runner = build_agent_runner(AgentRuntimeConfig(provider=AgentRuntimeProvider.DISABLED))

    assert isinstance(runner, FakeAgentRunner)


def test_agent_runner_factory_builds_openai_compatible_runner_from_env() -> None:
    runner = build_agent_runner(
        _supported_config(),
        environ={"QAESTRO_AGENT_API_KEY": "super-secret-token"},
        openai_compatible_client=RecordingOpenAICompatibleClient(OpenAICompatibleClientResponse(output_text="ok")),
    )

    assert isinstance(runner, OpenAICompatibleAgentRunner)


def test_agent_runner_factory_rejects_github_copilot_as_unsupported_provider() -> None:
    config = AgentRuntimeConfig(
        provider=AgentRuntimeProvider.GITHUB_COPILOT,
        model="copilot",
        credential_env_var="QAESTRO_COPILOT_TOKEN",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=64_000,
    )

    try:
        build_agent_runner(config, environ={"QAESTRO_COPILOT_TOKEN": "super-secret-token"})
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("GitHub Copilot provider should be unsupported for non-interactive runtime")

    assert "GitHub Copilot is not supported as a non-interactive Agent Runtime provider yet." in message
    assert "super-secret-token" not in message
