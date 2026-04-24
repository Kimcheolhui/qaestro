"""Background job execution and Agent Framework runner host.

Entry point for the ``qaestro-worker`` console script.
"""

from __future__ import annotations

import sys

from ...shared import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Start the worker process."""
    setup_logging()
    logger.info("qaestro-worker starting")
    # TODO(step-1): wire up actual task queue / runner
    logger.info("qaestro-worker ready — no runner configured yet, exiting")
    sys.exit(0)
