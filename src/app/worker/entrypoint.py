"""Console entrypoint for the background worker."""

from __future__ import annotations

import os
import socket
import sys

from src.shared import get_logger, load_config, setup_logging

from ..queue_factory import build_job_queue
from .factory import build_worker, check_worker_agent_runtime_health

logger = get_logger(__name__)


def default_redis_consumer_name() -> str:
    """Return a process-unique default Redis Streams consumer name."""
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> None:
    """Start the worker process."""
    cfg = load_config()
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)
    logger.info("qaestro-worker starting")
    agent_runtime_health = check_worker_agent_runtime_health(cfg)
    logger.info(
        "agent runtime health checked",
        extra={
            "agent_runtime_provider": agent_runtime_health.provider.value,
            "agent_runtime_status": agent_runtime_health.status.value,
            "agent_runtime_warnings": agent_runtime_health.warnings,
        },
    )
    queue = build_job_queue(cfg, consumer=cfg.redis_consumer or default_redis_consumer_name())
    worker = build_worker(cfg)
    if cfg.queue_backend == "memory":
        executions = worker.run_until_empty(queue)
        logger.info("qaestro-worker drained in-memory queue", extra={"job_count": len(executions)})
    else:
        logger.info("qaestro-worker consuming queue", extra={"queue_backend": cfg.queue_backend})
        worker.run_forever(queue)
    sys.exit(0)
