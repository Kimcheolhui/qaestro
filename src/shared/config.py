"""Environment-based configuration loader.

Loads configuration from environment variables with sensible defaults.
No external dependencies — uses only stdlib.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentRuntimeProvider(StrEnum):
    """Supported Agent Runtime provider families.

    ``DISABLED`` keeps local development and tests credential-free. Real
    providers are added behind ``runtime/agent`` adapters so core logic remains
    provider-neutral.
    """

    DISABLED = "disabled"
    AZURE_OPENAI = "azure-openai"
    GITHUB_COPILOT = "github-copilot"
    OPENAI_COMPATIBLE = "openai-compatible"


@dataclass(frozen=True, repr=False)
class AgentRuntimeConfig:
    """Agent Runtime settings loaded from ``QAESTRO_AGENT_*`` variables."""

    provider: AgentRuntimeProvider = AgentRuntimeProvider.DISABLED
    model: str = ""
    deployment: str = ""
    endpoint: str = ""
    base_url: str = ""
    api_version: str = ""
    credential_env_var: str = ""
    timeout_seconds: float = 60.0
    max_turns: int = 8
    max_tool_calls: int = 16
    temperature: float = 0.0

    def __repr__(self) -> str:
        credential = "<redacted>" if self.credential_env_var else ""
        return (
            "AgentRuntimeConfig("
            f"provider={self.provider!r}, "
            f"model={self.model!r}, "
            f"deployment={self.deployment!r}, "
            f"endpoint={self.endpoint!r}, "
            f"base_url={self.base_url!r}, "
            f"api_version={self.api_version!r}, "
            f"credential_env_var={credential}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_turns={self.max_turns!r}, "
            f"max_tool_calls={self.max_tool_calls!r}, "
            f"temperature={self.temperature!r}"
            ")"
        )


@dataclass(frozen=True, repr=False)
class AppConfig:
    """Top-level application configuration.

    All values come from environment variables with ``QAESTRO_`` prefix.
    Defaults are suitable for local development.
    """

    # ── General ────────────────────────────────────────────────────
    env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: str = "json"

    # ── Gateway ────────────────────────────────────────────────────
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    github_webhook_secret: str = ""

    # ── GitHub App auth ────────────────────────────────────────────
    # App ID and installation ID issued by GitHub when the App is
    # installed on a repository/org. ``private_key_path`` points to a
    # PEM file on disk (not the PEM body itself) — keeps secrets out of
    # environment variables and aligns with K8s secret-mount patterns.
    github_app_id: int = 0
    github_app_installation_id: int = 0
    github_app_private_key_path: str = ""

    # ── Worker / queue ─────────────────────────────────────────────
    worker_concurrency: int = 4
    queue_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream: str = "qaestro:jobs"
    redis_consumer_group: str = "qaestro-workers"
    redis_consumer: str = ""
    redis_read_block_ms: int = 5000
    redis_claim_idle_ms: int = 300000

    # ── Agent Runtime ──────────────────────────────────────────────
    agent_runtime: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)

    # ── Feature flags (for future use) ─────────────────────────────
    features: dict[str, bool] = field(default_factory=dict)

    def __repr__(self) -> str:
        fields = (
            f"env={self.env!r}",
            f"debug={self.debug!r}",
            f"log_level={self.log_level!r}",
            f"log_format={self.log_format!r}",
            f"gateway_host={self.gateway_host!r}",
            f"gateway_port={self.gateway_port!r}",
            f"github_webhook_secret={'<redacted>' if self.github_webhook_secret else ''}",
            f"github_app_id={self.github_app_id!r}",
            f"github_app_installation_id={self.github_app_installation_id!r}",
            f"github_app_private_key_path={self.github_app_private_key_path!r}",
            f"worker_concurrency={self.worker_concurrency!r}",
            f"queue_backend={self.queue_backend!r}",
            f"redis_url={self.redis_url!r}",
            f"redis_stream={self.redis_stream!r}",
            f"redis_consumer_group={self.redis_consumer_group!r}",
            f"redis_consumer={self.redis_consumer!r}",
            f"redis_read_block_ms={self.redis_read_block_ms!r}",
            f"redis_claim_idle_ms={self.redis_claim_idle_ms!r}",
            f"agent_runtime={self.agent_runtime!r}",
            f"features={self.features!r}",
        )
        return f"AppConfig({', '.join(fields)})"


_ENV_PREFIX = "QAESTRO_"

# Mapping: config field name → (env var suffix, type converter)
_ENV_MAP: dict[str, tuple[str, type[Any]]] = {
    "env": ("ENV", str),
    "debug": ("DEBUG", bool),
    "log_level": ("LOG_LEVEL", str),
    "log_format": ("LOG_FORMAT", str),
    "gateway_host": ("GATEWAY_HOST", str),
    "gateway_port": ("GATEWAY_PORT", int),
    "github_webhook_secret": ("GITHUB_WEBHOOK_SECRET", str),
    "github_app_id": ("GITHUB_APP_ID", int),
    "github_app_installation_id": ("GITHUB_APP_INSTALLATION_ID", int),
    "github_app_private_key_path": ("GITHUB_APP_PRIVATE_KEY_PATH", str),
    "worker_concurrency": ("WORKER_CONCURRENCY", int),
    "queue_backend": ("QUEUE_BACKEND", str),
    "redis_url": ("REDIS_URL", str),
    "redis_stream": ("REDIS_STREAM", str),
    "redis_consumer_group": ("REDIS_CONSUMER_GROUP", str),
    "redis_consumer": ("REDIS_CONSUMER", str),
    "redis_read_block_ms": ("REDIS_READ_BLOCK_MS", int),
    "redis_claim_idle_ms": ("REDIS_CLAIM_IDLE_MS", int),
}

_AGENT_ENV_MAP: dict[str, tuple[str, type[Any]]] = {
    "provider": ("AGENT_PROVIDER", AgentRuntimeProvider),
    "model": ("AGENT_MODEL", str),
    "deployment": ("AGENT_DEPLOYMENT", str),
    "endpoint": ("AGENT_ENDPOINT", str),
    "base_url": ("AGENT_BASE_URL", str),
    "api_version": ("AGENT_API_VERSION", str),
    "credential_env_var": ("AGENT_CREDENTIAL_ENV_VAR", str),
    "timeout_seconds": ("AGENT_TIMEOUT_SECONDS", float),
    "max_turns": ("AGENT_MAX_TURNS", int),
    "max_tool_calls": ("AGENT_MAX_TOOL_CALLS", int),
    "temperature": ("AGENT_TEMPERATURE", float),
}


def _parse_bool(value: str) -> bool:
    """Parse a boolean from an environment variable string."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def _convert_env_value(env_key: str, raw: str, converter: type[Any]) -> Any:
    if converter is bool:
        return _parse_bool(raw)
    if converter is int:
        try:
            return int(raw)
        except ValueError:
            msg = f"Invalid integer value for {env_key}: {raw!r}"
            raise ValueError(msg) from None
    if converter is float:
        try:
            return float(raw)
        except ValueError:
            msg = f"Invalid float value for {env_key}: {raw!r}"
            raise ValueError(msg) from None
    if converter is AgentRuntimeProvider:
        try:
            return AgentRuntimeProvider(raw)
        except ValueError:
            allowed = ", ".join(provider.value for provider in AgentRuntimeProvider)
            msg = f"Invalid Agent Runtime provider for {env_key}: {raw!r}. Expected one of: {allowed}"
            raise ValueError(msg) from None
    return raw


def _load_agent_runtime_config() -> AgentRuntimeConfig:
    overrides: dict[str, Any] = {}
    for field_name, (suffix, converter) in _AGENT_ENV_MAP.items():
        env_key = f"{_ENV_PREFIX}{suffix}"
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        overrides[field_name] = _convert_env_value(env_key, raw, converter)
    return AgentRuntimeConfig(**overrides)


def load_config() -> AppConfig:
    """Build an :class:`AppConfig` from environment variables.

    Environment variable names follow the pattern ``QAESTRO_<SUFFIX>``
    where *SUFFIX* is the uppercase field name (see ``_ENV_MAP``).

    Returns a frozen dataclass — immutable after creation.
    """
    overrides: dict[str, Any] = {}

    for field_name, (suffix, converter) in _ENV_MAP.items():
        env_key = f"{_ENV_PREFIX}{suffix}"
        raw = os.environ.get(env_key)
        if raw is None:
            continue

        overrides[field_name] = _convert_env_value(env_key, raw, converter)

    overrides["agent_runtime"] = _load_agent_runtime_config()
    return AppConfig(**overrides)
