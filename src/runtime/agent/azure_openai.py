"""Azure OpenAI Agent Runtime provider adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from src.runtime.agent.health import LiveSmokeProbeStatus
from src.runtime.agent.types import AgentRunInput, AgentRunResult, AgentRunStatus, AgentSessionHandle, AgentSessionScope
from src.runtime.stages import WorkflowStage
from src.shared.config import AgentRuntimeConfig


@dataclass(frozen=True)
class AzureOpenAIClientResponse:
    """Azure provider-adapter response normalized before entering qaestro contracts."""

    output_text: str
    error: str = ""


class AzureOpenAIChatClient(Protocol):
    """Minimal mocked/live client seam for Azure OpenAI responses."""

    def complete(self, request: dict[str, object]) -> AzureOpenAIClientResponse: ...


@dataclass(frozen=True)
class AzureOpenAILiveSmokeResult:
    """Result of an explicit Azure OpenAI live smoke probe."""

    status: LiveSmokeProbeStatus
    output_text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status is LiveSmokeProbeStatus.SUCCEEDED


class AzureOpenAIAgentRunner:
    """Provider-neutral runner backed by an Azure OpenAI client seam."""

    def __init__(self, *, config: AgentRuntimeConfig, client: AzureOpenAIChatClient, credential: str) -> None:
        self._config = config
        self._client = client
        self._credential = credential

    def start_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        return handle

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        try:
            response = self._client.complete(
                _request_for(self._config, session=session, run_input=run_input, self_credential=self._credential)
            )
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


class AzureOpenAIHTTPClient:
    """Small stdlib live client for opt-in Azure OpenAI smoke probes.

    The configured endpoint is expected to be the Azure OpenAI v1 base URL
    (for example ``https://resource.openai.azure.com/openai/v1``), and this
    client calls its ``/responses`` endpoint with the configured deployment as
    the model. This is intentionally isolated behind ``AzureOpenAIChatClient``
    so provider SDK or HTTP details do not leak into qaestro's provider-neutral
    contracts.
    """

    def __init__(self, *, credential: str) -> None:
        self._credential = credential

    def complete(self, request: dict[str, object]) -> AzureOpenAIClientResponse:
        endpoint = str(request["endpoint"]).rstrip("/")
        url = f"{endpoint}/responses"
        body = {
            "model": str(request["deployment"]),
            "input": str(request["prompt"]),
            "temperature": request["temperature"],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": self._credential,
            },
            method="POST",
        )
        timeout_value = request["timeout_seconds"]
        timeout = float(timeout_value) if isinstance(timeout_value, int | float | str) else 60.0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return AzureOpenAIClientResponse(output_text="", error=f"Azure OpenAI HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return AzureOpenAIClientResponse(output_text="", error=str(exc))
        return AzureOpenAIClientResponse(output_text=_extract_output_text(payload))


def run_azure_openai_live_smoke(
    config: AgentRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    client: AzureOpenAIChatClient | None = None,
    opt_in_live_smoke: bool = False,
) -> AzureOpenAILiveSmokeResult:
    """Run one explicit Azure OpenAI smoke completion when opted in."""

    if not opt_in_live_smoke:
        return AzureOpenAILiveSmokeResult(status=LiveSmokeProbeStatus.NOT_REQUESTED)

    env = os.environ if environ is None else environ
    credential = env.get(config.credential_env_var, "")
    smoke_client = client or AzureOpenAIHTTPClient(credential=credential)
    session = AgentSessionHandle(
        session_id="azure-openai-live-smoke",
        scope=AgentSessionScope.STAGE,
        repo_full_name="",
        pr_number=0,
        head_sha="",
        trigger="live-smoke",
        correlation_id="azure-openai-live-smoke",
    )
    run_input = AgentRunInput(
        stage=WorkflowStage.VALIDATOR,
        prompt="Respond with exactly: qaestro-live-smoke-ok",
        correlation_id="azure-openai-live-smoke",
        max_turns=1,
        max_tool_calls=0,
        timeout_seconds=config.timeout_seconds,
    )
    try:
        response = smoke_client.complete(
            _request_for(config, session=session, run_input=run_input, self_credential=credential)
        )
    except Exception as exc:
        return AzureOpenAILiveSmokeResult(
            status=LiveSmokeProbeStatus.FAILED,
            error=_redact_secret(str(exc), credential),
        )
    if response.error:
        return AzureOpenAILiveSmokeResult(
            status=LiveSmokeProbeStatus.FAILED,
            error=_redact_secret(response.error, credential),
        )
    return AzureOpenAILiveSmokeResult(status=LiveSmokeProbeStatus.SUCCEEDED, output_text=response.output_text)


def _request_for(
    config: AgentRuntimeConfig,
    *,
    session: AgentSessionHandle,
    run_input: AgentRunInput,
    self_credential: str,
) -> dict[str, object]:
    _ = session
    return {
        "endpoint": config.endpoint,
        "deployment": config.deployment,
        "model": config.model,
        "api_version": config.api_version,
        "prompt": run_input.prompt,
        "stage": run_input.stage.value,
        "correlation_id": run_input.correlation_id,
        "timeout_seconds": config.timeout_seconds if run_input.timeout_seconds is None else run_input.timeout_seconds,
        "max_turns": config.max_turns if run_input.max_turns is None else run_input.max_turns,
        "max_tool_calls": config.max_tool_calls if run_input.max_tool_calls is None else run_input.max_tool_calls,
        "temperature": config.temperature,
        "tool_names": run_input.allowed_tool_names,
        "credential_present": bool(self_credential),
    }


def _extract_output_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                    chunks.append(content_item["text"])
        return "".join(chunks)
    return ""


def _redact_secret(value: str, secret: str) -> str:
    if not secret:
        return value
    return value.replace(secret, "<redacted>")
