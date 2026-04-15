"""Environment-based configuration loader.

Loads configuration from environment variables with sensible defaults.
No external dependencies — uses only stdlib.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration.

    All values come from environment variables with ``DEVCLAW_`` prefix.
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

    # ── Worker ─────────────────────────────────────────────────────
    worker_concurrency: int = 4

    # ── Feature flags (for future use) ─────────────────────────────
    features: dict[str, bool] = field(default_factory=dict)


_ENV_PREFIX = "DEVCLAW_"

# Mapping: config field name → (env var suffix, type converter)
_ENV_MAP: dict[str, tuple[str, type[Any]]] = {
    "env": ("ENV", str),
    "debug": ("DEBUG", bool),
    "log_level": ("LOG_LEVEL", str),
    "log_format": ("LOG_FORMAT", str),
    "gateway_host": ("GATEWAY_HOST", str),
    "gateway_port": ("GATEWAY_PORT", int),
    "github_webhook_secret": ("GITHUB_WEBHOOK_SECRET", str),
    "worker_concurrency": ("WORKER_CONCURRENCY", int),
}


def _parse_bool(value: str) -> bool:
    """Parse a boolean from an environment variable string."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> AppConfig:
    """Build an :class:`AppConfig` from environment variables.

    Environment variable names follow the pattern ``DEVCLAW_<SUFFIX>``
    where *SUFFIX* is the uppercase field name (see ``_ENV_MAP``).

    Returns a frozen dataclass — immutable after creation.
    """
    overrides: dict[str, Any] = {}

    for field_name, (suffix, converter) in _ENV_MAP.items():
        env_key = f"{_ENV_PREFIX}{suffix}"
        raw = os.environ.get(env_key)
        if raw is None:
            continue

        if converter is bool:
            overrides[field_name] = _parse_bool(raw)
        elif converter is int:
            try:
                overrides[field_name] = int(raw)
            except ValueError:
                msg = f"Invalid integer value for {env_key}: {raw!r}"
                raise ValueError(msg) from None
        else:
            overrides[field_name] = raw

    return AppConfig(**overrides)
