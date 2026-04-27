"""Queue factory used by gateway and worker entrypoints."""

from __future__ import annotations

from src.shared.config import AppConfig

from .jobs import InMemoryJobQueue, JobQueue, RedisStreamsJobQueue


def build_job_queue(cfg: AppConfig, *, consumer: str | None = None) -> JobQueue:
    """Build the configured job queue implementation.

    ``memory`` is for single-process local/test wiring. ``redis-streams`` is the
    shared queue used when gateway and worker run as separate processes.
    """
    if cfg.queue_backend == "memory":
        return InMemoryJobQueue()
    if cfg.queue_backend == "redis-streams":
        return RedisStreamsJobQueue.from_url(
            cfg.redis_url,
            stream=cfg.redis_stream,
            group=cfg.redis_consumer_group,
            consumer=consumer or cfg.redis_consumer,
            read_block_ms=cfg.redis_read_block_ms,
            claim_idle_ms=cfg.redis_claim_idle_ms,
        )
    raise ValueError(f"Unsupported queue backend: {cfg.queue_backend!r}")
