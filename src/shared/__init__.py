"""Shared utilities — config, logging, tracing, common helpers.

Re-exports the public API so consumers can do::

    from src.shared import load_config, get_logger, new_correlation_id
"""

from src.shared.config import AppConfig, load_config
from src.shared.logging import get_logger, setup_logging
from src.shared.tracing import get_correlation_id, new_correlation_id, set_correlation_id

__all__ = [
    "AppConfig",
    "get_correlation_id",
    "get_logger",
    "load_config",
    "new_correlation_id",
    "set_correlation_id",
    "setup_logging",
]
