"""Agent Runtime capability policy and offline health checks."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider

RECOMMENDED_CONTEXT_WINDOW_TOKENS = 32_000


class AgentRuntimeHealthStatus(StrEnum):
    """Offline health state for an Agent Runtime configuration."""

    DISABLED = "disabled"
    SUPPORTED = "supported"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class LiveSmokeProbeStatus(StrEnum):
    """Whether an opt-in live provider smoke probe actually ran."""

    NOT_REQUESTED = "not_requested"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass(frozen=True)
class AgentRuntimeHealthResult:
    """Secret-safe result of checking Agent Runtime readiness.

    This check is intentionally offline by default. Live provider calls can cost
    money and require network credentials, so provider smoke probes must be
    explicitly opted in by a future adapter-specific path.
    """

    provider: AgentRuntimeProvider
    status: AgentRuntimeHealthStatus
    actionable_errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    live_smoke_probe_status: LiveSmokeProbeStatus = LiveSmokeProbeStatus.NOT_REQUESTED

    @property
    def ok(self) -> bool:
        return self.status in {AgentRuntimeHealthStatus.SUPPORTED, AgentRuntimeHealthStatus.DEGRADED}


def check_agent_runtime_health(
    config: AgentRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    opt_in_live_smoke: bool = False,
) -> AgentRuntimeHealthResult:
    """Validate whether ``config`` can support qaestro Agent Runtime execution.

    The policy verifies only configuration and declared capabilities. It does
    not perform a live LLM call unless a provider adapter later implements the
    explicit ``opt_in_live_smoke`` path.
    """

    env = os.environ if environ is None else environ
    if config.provider is AgentRuntimeProvider.DISABLED:
        return AgentRuntimeHealthResult(
            provider=config.provider,
            status=AgentRuntimeHealthStatus.DISABLED,
            warnings=("Agent Runtime is disabled; runtime validation will not call an LLM provider.",),
        )

    provider_errors = _provider_config_errors(config, env)
    warnings = list(_capability_warnings(config))
    if provider_errors:
        return AgentRuntimeHealthResult(
            provider=config.provider,
            status=AgentRuntimeHealthStatus.UNSUPPORTED,
            actionable_errors=provider_errors,
            warnings=tuple(warnings),
        )

    capability_errors = _capability_errors(config)
    if capability_errors:
        return AgentRuntimeHealthResult(
            provider=config.provider,
            status=AgentRuntimeHealthStatus.UNSUPPORTED,
            actionable_errors=capability_errors,
            warnings=tuple(warnings),
        )

    if opt_in_live_smoke:
        warnings.append("Live provider smoke check was requested but no provider adapter implements it yet.")
        live_smoke_probe_status = LiveSmokeProbeStatus.NOT_IMPLEMENTED
    else:
        warnings.append(
            "Live provider smoke check not executed; set opt_in_live_smoke=True to probe provider connectivity."
        )
        live_smoke_probe_status = LiveSmokeProbeStatus.NOT_REQUESTED

    return AgentRuntimeHealthResult(
        provider=config.provider,
        status=AgentRuntimeHealthStatus.DEGRADED
        if warnings and _has_degradation_warning(warnings)
        else AgentRuntimeHealthStatus.SUPPORTED,
        warnings=tuple(warnings),
        live_smoke_probe_status=live_smoke_probe_status,
    )


def _provider_config_errors(config: AgentRuntimeConfig, env: Mapping[str, str]) -> tuple[str, ...]:
    errors: list[str] = []
    if config.provider is AgentRuntimeProvider.AZURE_OPENAI:
        if not config.endpoint:
            errors.append("Azure OpenAI endpoint is required for QAESTRO_AGENT_ENDPOINT.")
        if not config.deployment:
            errors.append("Azure OpenAI deployment is required for QAESTRO_AGENT_DEPLOYMENT.")
        if not config.api_version:
            errors.append("Azure OpenAI API version is required for QAESTRO_AGENT_API_VERSION.")
    elif config.provider is AgentRuntimeProvider.OPENAI_COMPATIBLE:
        if not config.base_url:
            errors.append("OpenAI-compatible base URL is required for QAESTRO_AGENT_BASE_URL.")
        if not config.model:
            errors.append("OpenAI-compatible model is required for QAESTRO_AGENT_MODEL.")
    elif config.provider is AgentRuntimeProvider.GITHUB_COPILOT:
        return ("GitHub Copilot is not supported as a non-interactive Agent Runtime provider yet.",)

    if not config.credential_env_var:
        errors.append("Credential environment variable name is required for QAESTRO_AGENT_CREDENTIAL_ENV_VAR.")
    elif not env.get(config.credential_env_var):
        errors.append(f"Credential environment variable {config.credential_env_var} is not set.")
    return tuple(errors)


def _capability_errors(config: AgentRuntimeConfig) -> tuple[str, ...]:
    errors: list[str] = []
    if not config.supports_tool_calling:
        errors.append("tool calling is required")
    if not config.supports_structured_output:
        errors.append("structured output or schema-constrained responses are required")
    if config.context_window_tokens <= 0:
        errors.append("context window token capacity is required for QAESTRO_AGENT_CONTEXT_WINDOW_TOKENS.")
    return tuple(errors)


def _capability_warnings(config: AgentRuntimeConfig) -> tuple[str, ...]:
    if 0 < config.context_window_tokens < RECOMMENDED_CONTEXT_WINDOW_TOKENS:
        return (
            f"Configured context window {config.context_window_tokens} tokens is below the recommended "
            f"{RECOMMENDED_CONTEXT_WINDOW_TOKENS} tokens.",
        )
    return ()


def _has_degradation_warning(warnings: list[str]) -> bool:
    return any("context window" in warning for warning in warnings)
