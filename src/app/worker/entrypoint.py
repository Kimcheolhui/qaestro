"""Console entrypoint for the background worker."""

from __future__ import annotations

import sys

from src.shared import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Start the worker process."""
    setup_logging()
    logger.info("qaestro-worker starting")
    # TODO(Step 2 deployment wiring): connect this entrypoint to a durable queue
    # and GitHub App credentials. Unit-tested worker orchestration lives in
    # ``runner.py`` and is intentionally side-effect free by default.
    logger.info("qaestro-worker ready — no durable queue configured yet, exiting")
    sys.exit(0)
