"""Shared application job contracts used by gateway and worker."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from src.core.contracts import (
    ChatMention,
    CICompleted,
    Event,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    PRCommented,
    PREvent,
    PROpened,
    PRReviewed,
    PRUpdated,
)


@dataclass(frozen=True)
class EventJob:
    """Retryable worker input created from a normalized event.

    The gateway stores normalized events in this small envelope so retry logic
    can preserve correlation id and event metadata without depending on raw
    provider payloads. ``delivery_id`` is populated by durable queue adapters
    after dequeue so the worker can acknowledge the exact message it processed.
    """

    event: Event
    correlation_id: str
    delivery_id: str = ""


@dataclass(frozen=True)
class MalformedEventJob:
    """Queue message that could not be decoded into an :class:`EventJob`.

    Durable queues may contain stale messages after schema changes or manual
    repair attempts. Returning this sentinel lets the worker record a terminal
    failure and acknowledge the poison message instead of crashing and
    reclaiming it forever.
    """

    delivery_id: str
    error: str


QueuedJob = EventJob | MalformedEventJob


class EnqueueQueue(Protocol):
    """Minimal enqueue-only queue surface required by the gateway."""

    def enqueue(self, job: EventJob) -> None: ...


class JobQueue(EnqueueQueue, Protocol):
    """Queue contract shared by gateway and worker.

    Implementations may be in-memory for tests or durable/shared for separate
    gateway and worker processes. Durable queues should keep unacknowledged jobs
    recoverable until :meth:`ack` is called.
    """

    def dequeue(self) -> QueuedJob | None: ...

    def ack(self, job: QueuedJob) -> None: ...


class InMemoryJobQueue:
    """FIFO queue for tests, local development, and Step 2 single-process wiring."""

    def __init__(self, jobs: Iterable[EventJob] = ()) -> None:
        self._jobs: deque[EventJob] = deque(jobs)

    def enqueue(self, job: EventJob) -> None:
        self._jobs.append(job)

    def dequeue(self) -> EventJob | None:
        if not self._jobs:
            return None
        return self._jobs.popleft()

    def ack(self, job: QueuedJob) -> None:
        """No-op ack for the non-durable in-memory queue."""
        _ = job

    def __len__(self) -> int:
        return len(self._jobs)


class RedisClient(Protocol):
    """Subset of redis-py used by :class:`RedisStreamsJobQueue`."""

    def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> Any: ...

    def xadd(self, stream: str, fields: dict[str, str]) -> Any: ...

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int,
        block: int,
    ) -> list[tuple[Any, list[tuple[Any, Mapping[Any, Any]]]]]: ...

    def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str,
        count: int,
    ) -> tuple[Any, list[tuple[Any, Mapping[Any, Any]]], list[Any]]: ...

    def xack(self, stream: str, group: str, message_id: str) -> Any: ...


class RedisStreamsJobQueue:
    """Durable/shared job queue backed by Redis Streams.

    The gateway uses ``XADD`` to append jobs. Workers use a consumer group,
    claim stale pending messages first, then read new messages. A message is
    acknowledged only after worker processing returns.
    """

    def __init__(
        self,
        *,
        redis_client: RedisClient,
        stream: str = "qaestro:jobs",
        group: str = "qaestro-workers",
        consumer: str = "qaestro-worker",
        read_block_ms: int = 5000,
        claim_idle_ms: int = 30000,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._read_block_ms = read_block_ms
        self._claim_idle_ms = claim_idle_ms
        self._claim_start_id = "0-0"
        self._ensure_group()

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        stream: str = "qaestro:jobs",
        group: str = "qaestro-workers",
        consumer: str = "qaestro-worker",
        read_block_ms: int = 5000,
        claim_idle_ms: int = 30000,
    ) -> RedisStreamsJobQueue:
        """Create a Redis Streams queue from a redis-py URL."""
        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
            raise RuntimeError("Redis Streams queue requires the 'redis' package") from exc

        return cls(
            redis_client=Redis.from_url(redis_url),
            stream=stream,
            group=group,
            consumer=consumer,
            read_block_ms=read_block_ms,
            claim_idle_ms=claim_idle_ms,
        )

    def enqueue(self, job: EventJob) -> None:
        self._redis.xadd(self._stream, {"job": _serialize_job(job)})

    def dequeue(self) -> QueuedJob | None:
        pending = self._claim_pending()
        if pending is not None:
            return pending

        streams = self._redis.xreadgroup(
            groupname=self._group,
            consumername=self._consumer,
            streams={self._stream: ">"},
            count=1,
            block=self._read_block_ms,
        )
        return self._job_from_streams(streams)

    def ack(self, job: QueuedJob) -> None:
        if job.delivery_id:
            self._redis.xack(self._stream, self._group, job.delivery_id)

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(self._stream, self._group, "0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _claim_pending(self) -> QueuedJob | None:
        next_start_id, messages, _ = self._redis.xautoclaim(
            name=self._stream,
            groupname=self._group,
            consumername=self._consumer,
            min_idle_time=self._claim_idle_ms,
            start_id=self._claim_start_id,
            count=1,
        )
        self._claim_start_id = _to_str(next_start_id)
        if not messages:
            return None
        return _job_from_message(messages[0])

    def _job_from_streams(self, streams: list[tuple[Any, list[tuple[Any, Mapping[Any, Any]]]]]) -> QueuedJob | None:
        if not streams:
            return None
        _, messages = streams[0]
        if not messages:
            return None
        return _job_from_message(messages[0])


def _job_from_message(message: tuple[Any, Mapping[Any, Any]]) -> QueuedJob:
    message_id, fields = message
    delivery_id = _to_str(message_id)
    try:
        payload = _field_value(fields, "job")
        return _deserialize_job(payload, delivery_id=delivery_id)
    except Exception as exc:
        return MalformedEventJob(delivery_id=delivery_id, error=str(exc))


def _serialize_job(job: EventJob) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "correlation_id": job.correlation_id,
            "event": _event_to_payload(job.event),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize_job(payload: str, *, delivery_id: str = "") -> EventJob:
    data = json.loads(payload)
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported job schema version: {schema_version!r}")
    event = _event_from_payload(data["event"])
    return EventJob(event=event, correlation_id=str(data["correlation_id"]), delivery_id=delivery_id)


def _event_to_payload(event: Event) -> dict[str, Any]:
    data = asdict(event)
    meta = data["meta"]
    meta["event_type"] = event.meta.event_type.value
    meta["source"] = event.meta.source.value
    meta["timestamp"] = event.meta.timestamp.isoformat()
    data["meta"] = meta
    data["kind"] = event.meta.event_type.value
    return data


def _event_from_payload(data: Mapping[str, Any]) -> Event:
    kind = EventType(str(data["kind"]))
    meta = _meta_from_payload(data["meta"])
    if kind in {EventType.PR_OPENED, EventType.PR_UPDATED}:
        pr_event = _pr_event_from_payload(kind, meta, data)
        if isinstance(pr_event, PROpened | PRUpdated):
            return pr_event
        raise ValueError(f"Unsupported PR event type: {kind.value}")
    if kind is EventType.PR_COMMENTED:
        return PRCommented(meta=meta, **_without(data, "kind", "meta"))
    if kind is EventType.PR_REVIEWED:
        return PRReviewed(meta=meta, **_without(data, "kind", "meta"))
    if kind is EventType.CI_COMPLETED:
        values = _without(data, "kind", "meta")
        values["failed_jobs"] = tuple(values.get("failed_jobs", ()))
        return CICompleted(meta=meta, **values)
    if kind is EventType.CHAT_MENTION:
        return ChatMention(meta=meta, **_without(data, "kind", "meta"))
    raise ValueError(f"Unsupported event type: {kind.value}")


def _pr_event_from_payload(kind: EventType, meta: EventMeta, data: Mapping[str, Any]) -> PREvent:
    values = _without(data, "kind", "meta")
    values["files_changed"] = tuple(FileChange(**file_data) for file_data in values.get("files_changed", ()))
    event_cls = PROpened if kind is EventType.PR_OPENED else PRUpdated
    return event_cls(meta=meta, **values)


def _meta_from_payload(data: Mapping[str, Any]) -> EventMeta:
    return EventMeta(
        event_id=str(data["event_id"]),
        event_type=EventType(str(data["event_type"])),
        correlation_id=str(data["correlation_id"]),
        timestamp=datetime.fromisoformat(str(data["timestamp"])),
        source=EventSource(str(data["source"])),
    )


def _without(data: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    omitted = set(keys)
    return {str(key): value for key, value in data.items() if key not in omitted}


def _field_value(fields: Mapping[Any, Any], key: str) -> str:
    if key in fields:
        return _to_str(fields[key])
    encoded_key = key.encode("utf-8")
    if encoded_key in fields:
        return _to_str(fields[encoded_key])
    raise ValueError(f"Redis stream message is missing field: {key}")


def _to_str(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
