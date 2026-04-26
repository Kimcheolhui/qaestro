"""Console entrypoint for the background worker."""

from __future__ import annotations

import socket
import sys

from src.app.queue_factory import build_job_queue
from src.app.worker.factory import build_worker
from src.shared import get_logger, load_config, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Start the worker process."""
    cfg = load_config()
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)
    logger.info("qaestro-worker starting")
    queue = build_job_queue(cfg, consumer=cfg.redis_consumer or socket.gethostname())
    worker = build_worker(cfg)
    if cfg.queue_backend == "memory":
        executions = worker.run_until_empty(queue)
        logger.info("qaestro-worker drained in-memory queue", extra={"job_count": len(executions)})
    else:
        logger.info("qaestro-worker consuming queue", extra={"queue_backend": cfg.queue_backend})
        worker.run_forever(queue)
    sys.exit(0)
