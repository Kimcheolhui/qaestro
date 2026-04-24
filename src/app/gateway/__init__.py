"""Webhook receiver and event normalizer.

Entry point for the ``qaestro-gateway`` console script.
"""

from __future__ import annotations

import sys

from ...shared import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Start the gateway HTTP server."""
    setup_logging()
    logger.info("qaestro-gateway starting")
    # TODO(step-1): wire up actual ASGI/webhook server
    logger.info("qaestro-gateway ready — no handler configured yet, exiting")
    sys.exit(0)
