"""Shared utilities — config, logging, tracing, common helpers.

Re-exports the public API so consumers can do::

    from src.shared import load_config, get_logger, new_correlation_id
"""

from .config import AgentRuntimeConfig, AgentRuntimeProvider, AppConfig, load_config
from .logging import get_logger, setup_logging
from .redaction import SecretRedactor, redact_text, redact_value
from .tracing import get_correlation_id, new_correlation_id, set_correlation_id

__all__ = [
    "AgentRuntimeConfig",
    "AgentRuntimeProvider",
    "AppConfig",
    "SecretRedactor",
    "get_correlation_id",
    "get_logger",
    "load_config",
    "new_correlation_id",
    "redact_text",
    "redact_value",
    "set_correlation_id",
    "setup_logging",
]
