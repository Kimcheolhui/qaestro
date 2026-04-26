"""Console entrypoint for the GitHub webhook gateway."""

from __future__ import annotations

import sys

from src.app.gateway.github import GitHubWebhookGateway
from src.app.gateway.server import serve_github_webhook
from src.app.queue_factory import build_job_queue
from src.shared import get_logger, load_config, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Start the gateway HTTP server."""
    cfg = load_config()
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)
    logger.info("qaestro-gateway starting")
    queue = build_job_queue(cfg)
    gateway = GitHubWebhookGateway(secret=cfg.github_webhook_secret, queue=queue)
    logger.info("qaestro-gateway serving GitHub webhook endpoint")
    serve_github_webhook(gateway, host=cfg.gateway_host, port=cfg.gateway_port)
    sys.exit(0)
