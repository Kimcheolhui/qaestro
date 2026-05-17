"""Tests for Azure OpenAI Agent Runtime provider adapter."""

from __future__ import annotations

from src.runtime.agent import (
    AgentRunInput,
    AgentRunStatus,
    AgentSessionHandle,
    AgentSessionScope,
    AzureOpenAIAgentRunner,
    AzureOpenAIChatClient,
    AzureOpenAIClientResponse,
    AzureOpenAILiveSmokeResult,
    LiveSmokeProbeStatus,
    build_agent_runner,
    run_azure_openai_live_smoke,
)
from src.runtime.stages import WorkflowStage
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider


class RecordingAzureOpenAIClient(AzureOpenAIChatClient):
    def __init__(self, response: AzureOpenAIClientResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, request: dict[str, object]) -> AzureOpenAIClientResponse:
        self.calls.append(request)
        return self.response


class FailingAzureOpenAIClient(AzureOpenAIChatClient):
    def complete(self, request: dict[str, object]) -> AzureOpenAIClientResponse:
        _ = request
        raise TimeoutError("azure timed out with credential super-secret-token")


def _supported_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        provider=AgentRuntimeProvider.AZURE_OPENAI,
        endpoint="https://azure-openai.example.test/openai/v1",
        deployment="review-deployment",
        model="review-model",
        api_version="preview",
        credential_env_var="QAESTRO_AZURE_OPENAI_KEY",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window_tokens=128_000,
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
        pr_number=77,
        head_sha="abc123",
        trigger="manual",
        correlation_id="corr-1",
    )


def test_azure_openai_runner_builds_provider_neutral_request_without_secret_value() -> None:
    client = RecordingAzureOpenAIClient(AzureOpenAIClientResponse(output_text="azure analysis ok"))
    runner = AzureOpenAIAgentRunner(
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
    assert result.output_text == "azure analysis ok"
    assert result.stage is WorkflowStage.VALIDATOR
    assert client.calls == [
        {
            "endpoint": "https://azure-openai.example.test/openai/v1",
            "deployment": "review-deployment",
            "model": "review-model",
            "api_version": "preview",
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


def test_azure_openai_runner_preserves_explicit_zero_budgets() -> None:
    client = RecordingAzureOpenAIClient(AzureOpenAIClientResponse(output_text="azure analysis ok"))
    runner = AzureOpenAIAgentRunner(
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


def test_azure_openai_runner_normalizes_response_errors_without_secret_value() -> None:
    client = RecordingAzureOpenAIClient(
        AzureOpenAIClientResponse(output_text="", error="azure unavailable: super-secret-token")
    )
    runner = AzureOpenAIAgentRunner(
        config=_supported_config(),
        client=client,
        credential="super-secret-token",
    )

    result = runner.run(
        session=_session(),
        run_input=AgentRunInput(stage=WorkflowStage.VALIDATOR, prompt="Validate", correlation_id="corr-1"),
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error == "azure unavailable: <redacted>"


def test_azure_openai_runner_normalizes_client_exceptions_without_secret_value() -> None:
    runner = AzureOpenAIAgentRunner(
        config=_supported_config(),
        client=FailingAzureOpenAIClient(),
        credential="super-secret-token",
    )

    result = runner.run(
        session=_session(),
        run_input=AgentRunInput(stage=WorkflowStage.VALIDATOR, prompt="Validate", correlation_id="corr-1"),
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error == "azure timed out with credential <redacted>"


def test_agent_runner_factory_builds_azure_openai_runner_from_env() -> None:
    runner = build_agent_runner(
        _supported_config(),
        environ={"QAESTRO_AZURE_OPENAI_KEY": "super-secret-token"},
        azure_openai_client=RecordingAzureOpenAIClient(AzureOpenAIClientResponse(output_text="ok")),
    )

    assert isinstance(runner, AzureOpenAIAgentRunner)


def test_agent_runner_factory_requires_injected_azure_client_until_live_adapter_is_configured() -> None:
    try:
        build_agent_runner(_supported_config(), environ={"QAESTRO_AZURE_OPENAI_KEY": "super-secret-token"})
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("Azure OpenAI runner should require injected client before live adapter wiring")

    assert "Azure OpenAI runner requires an injected client until a live adapter is configured." in message
    assert "super-secret-token" not in message


def test_azure_openai_live_smoke_is_not_requested_by_default() -> None:
    client = RecordingAzureOpenAIClient(AzureOpenAIClientResponse(output_text="pong"))

    result = run_azure_openai_live_smoke(
        _supported_config(),
        environ={"QAESTRO_AZURE_OPENAI_KEY": "super-secret-token"},
        client=client,
        opt_in_live_smoke=False,
    )

    assert result.status is LiveSmokeProbeStatus.NOT_REQUESTED
    assert result.ok is False
    assert client.calls == []


def test_azure_openai_live_smoke_executes_only_when_opted_in_without_leaking_secret() -> None:
    client = RecordingAzureOpenAIClient(AzureOpenAIClientResponse(output_text="pong"))

    result = run_azure_openai_live_smoke(
        _supported_config(),
        environ={"QAESTRO_AZURE_OPENAI_KEY": "super-secret-token"},
        client=client,
        opt_in_live_smoke=True,
    )

    assert result == AzureOpenAILiveSmokeResult(status=LiveSmokeProbeStatus.SUCCEEDED, output_text="pong")
    assert client.calls[0]["prompt"] == "Respond with exactly: qaestro-live-smoke-ok"
    assert client.calls[0]["max_turns"] == 1
    assert client.calls[0]["max_tool_calls"] == 0
    assert "super-secret-token" not in repr(client.calls[0])
    assert "super-secret-token" not in repr(result)


def test_azure_openai_live_smoke_normalizes_failures_without_secret_value() -> None:
    result = run_azure_openai_live_smoke(
        _supported_config(),
        environ={"QAESTRO_AZURE_OPENAI_KEY": "super-secret-token"},
        client=FailingAzureOpenAIClient(),
        opt_in_live_smoke=True,
    )

    assert result.status is LiveSmokeProbeStatus.FAILED
    assert result.error == "azure timed out with credential <redacted>"
