"""Shared application job contracts used by gateway and worker."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol, cast

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


class RedisStreamClient(Protocol):
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
        redis_client: RedisStreamClient,
        stream: str = "qaestro:jobs",
        group: str = "qaestro-workers",
        consumer: str = "qaestro-worker",
        read_block_ms: int = 5000,
        claim_idle_ms: int = 30000,
        busy_group_error: type[Exception] = Exception,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._read_block_ms = read_block_ms
        self._claim_idle_ms = claim_idle_ms
        self._busy_group_error = busy_group_error
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
            from redis.exceptions import ResponseError
        except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
            raise RuntimeError("Redis Streams queue requires the 'redis' package") from exc

        return cls(
            redis_client=cast(RedisStreamClient, Redis.from_url(redis_url)),
            stream=stream,
            group=group,
            consumer=consumer,
            read_block_ms=read_block_ms,
            claim_idle_ms=claim_idle_ms,
            busy_group_error=ResponseError,
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
        except self._busy_group_error as exc:
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
    _require_mapping(data, "job")
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported job schema version: {schema_version!r}")
    event = _event_from_payload(_require_mapping(data.get("event"), "event"))
    return EventJob(
        event=event,
        correlation_id=_require_str(data.get("correlation_id"), "correlation_id"),
        delivery_id=delivery_id,
    )


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
    kind = EventType(_require_str(data.get("kind"), "kind"))
    meta = _meta_from_payload(_require_mapping(data.get("meta"), "meta"))
    if kind in {EventType.PR_OPENED, EventType.PR_UPDATED}:
        pr_event = _pr_event_from_payload(kind, meta, data)
        if isinstance(pr_event, PROpened | PRUpdated):
            return pr_event
        raise ValueError(f"Unsupported PR event type: {kind.value}")
    if kind is EventType.PR_COMMENTED:
        return PRCommented(
            meta=meta,
            repo_full_name=_require_str(data.get("repo_full_name"), "repo_full_name"),
            pr_number=_require_int(data.get("pr_number"), "pr_number"),
            comment_id=_require_int(data.get("comment_id"), "comment_id"),
            author=_require_str(data.get("author"), "author"),
            body=_require_str(data.get("body"), "body"),
            is_review_comment=_require_bool(data.get("is_review_comment", False), "is_review_comment"),
            path=_require_str(data.get("path", ""), "path"),
            line=_optional_int(data.get("line"), "line"),
        )
    if kind is EventType.PR_REVIEWED:
        return PRReviewed(
            meta=meta,
            repo_full_name=_require_str(data.get("repo_full_name"), "repo_full_name"),
            pr_number=_require_int(data.get("pr_number"), "pr_number"),
            reviewer=_require_str(data.get("reviewer"), "reviewer"),
            state=_require_str(data.get("state"), "state"),
            body=_require_str(data.get("body", ""), "body"),
        )
    if kind is EventType.CI_COMPLETED:
        return CICompleted(
            meta=meta,
            repo_full_name=_require_str(data.get("repo_full_name"), "repo_full_name"),
            pr_number=_optional_int(data.get("pr_number"), "pr_number"),
            commit_sha=_require_str(data.get("commit_sha"), "commit_sha"),
            workflow_name=_require_str(data.get("workflow_name"), "workflow_name"),
            conclusion=_require_str(data.get("conclusion"), "conclusion"),
            run_url=_require_str(data.get("run_url"), "run_url"),
            failed_jobs=_str_tuple(data.get("failed_jobs", ()), "failed_jobs"),
            logs_url=_require_str(data.get("logs_url", ""), "logs_url"),
        )
    if kind is EventType.CHAT_MENTION:
        return ChatMention(
            meta=meta,
            platform=_require_str(data.get("platform"), "platform"),
            channel_id=_require_str(data.get("channel_id"), "channel_id"),
            channel_name=_require_str(data.get("channel_name"), "channel_name"),
            author=_require_str(data.get("author"), "author"),
            message=_require_str(data.get("message"), "message"),
            thread_id=_require_str(data.get("thread_id", ""), "thread_id"),
            referenced_pr=_optional_int(data.get("referenced_pr"), "referenced_pr"),
        )
    raise ValueError(f"Unsupported event type: {kind.value}")


def _pr_event_from_payload(kind: EventType, meta: EventMeta, data: Mapping[str, Any]) -> PREvent:
    file_values = data.get("files_changed", ())
    if not isinstance(file_values, list | tuple):
        raise TypeError("files_changed must be a list or tuple")
    event_cls = PROpened if kind is EventType.PR_OPENED else PRUpdated
    return event_cls(
        meta=meta,
        repo_full_name=_require_str(data.get("repo_full_name"), "repo_full_name"),
        pr_number=_require_int(data.get("pr_number"), "pr_number"),
        title=_require_str(data.get("title"), "title"),
        body=_require_str(data.get("body"), "body"),
        author=_require_str(data.get("author"), "author"),
        base_branch=_require_str(data.get("base_branch"), "base_branch"),
        head_branch=_require_str(data.get("head_branch"), "head_branch"),
        diff_url=_require_str(data.get("diff_url"), "diff_url"),
        files_changed=tuple(
            _file_change_from_payload(file_data, f"files_changed[{index}]")
            for index, file_data in enumerate(file_values)
        ),
    )


def _file_change_from_payload(data: object, field: str) -> FileChange:
    values = _require_mapping(data, field)
    return FileChange(
        path=_require_str(values.get("path"), f"{field}.path"),
        status=_require_str(values.get("status"), f"{field}.status"),
        additions=_require_int(values.get("additions", 0), f"{field}.additions"),
        deletions=_require_int(values.get("deletions", 0), f"{field}.deletions"),
        previous_filename=_require_str(values.get("previous_filename", ""), f"{field}.previous_filename"),
    )


def _meta_from_payload(data: Mapping[str, Any]) -> EventMeta:
    return EventMeta(
        event_id=_require_str(data.get("event_id"), "meta.event_id"),
        event_type=EventType(_require_str(data.get("event_type"), "meta.event_type")),
        correlation_id=_require_str(data.get("correlation_id"), "meta.correlation_id"),
        timestamp=datetime.fromisoformat(_require_str(data.get("timestamp"), "meta.timestamp")),
        source=EventSource(_require_str(data.get("source"), "meta.source")),
    )


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def _require_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    return value


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field)


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _str_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{field} must be a list or tuple")
    return tuple(_require_str(item, f"{field}[{index}]") for index, item in enumerate(value))


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
