"""Tests for Redis Streams-backed worker queue."""

from __future__ import annotations

from datetime import UTC, datetime

from src.app.jobs import EventJob, MalformedEventJob, RedisStreamsJobQueue
from src.core.contracts import (
    ChatMention,
    CICompleted,
    Event,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    PRCommented,
    PROpened,
    PRReviewed,
    PRUpdated,
)


class FakeRedis:
    def __init__(self) -> None:
        self.group_created: tuple[str, str, str] | None = None
        self.added: list[tuple[str, dict[str, str]]] = []
        self.new_messages: list[tuple[bytes, dict[bytes, bytes]]] = []
        self.claimed_messages: list[tuple[bytes, dict[bytes, bytes]]] = []
        self.acked: list[tuple[str, str, str]] = []
        self.claim_start_ids: list[str] = []
        self.xgroup_create_error: Exception | None = None

    def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:
        assert mkstream is True
        self.group_created = (stream, group, id)
        if self.xgroup_create_error is not None:
            raise self.xgroup_create_error

    def xadd(self, stream: str, fields: dict[str, str]) -> bytes:
        self.added.append((stream, fields))
        return b"1700000000000-0"

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int,
        block: int,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        assert groupname == "qaestro-workers"
        assert consumername == "worker-1"
        assert streams == {"qaestro:jobs": ">"}
        assert count == 1
        assert block == 0
        if not self.new_messages:
            return []
        return [(b"qaestro:jobs", [self.new_messages.pop(0)])]

    def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str,
        count: int,
    ) -> tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]], list[bytes]]:
        assert name == "qaestro:jobs"
        assert groupname == "qaestro-workers"
        assert consumername == "worker-1"
        assert min_idle_time == 5000
        assert count == 1
        self.claim_start_ids.append(start_id)
        if not self.claimed_messages:
            return (b"0-0", [], [])
        return (b"1700000000002-0", [self.claimed_messages.pop(0)], [])

    def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append((stream, group, message_id))
        return 1


def _meta(event_type: EventType) -> EventMeta:
    return EventMeta(
        event_id=f"evt-{event_type.value}",
        event_type=event_type,
        correlation_id=f"corr-{event_type.value}",
        timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


def _pr_opened() -> PROpened:
    return PROpened(
        meta=_meta(EventType.PR_OPENED),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=34,
        title="feat: redis queue",
        body="queue body",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/redis-queue",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/34.diff",
        files_changed=(FileChange(path="src/app/jobs.py", status="modified", additions=20, deletions=2),),
    )


def _events() -> list[Event]:
    opened = _pr_opened()
    return [
        opened,
        PRUpdated(
            meta=_meta(EventType.PR_UPDATED),
            repo_full_name=opened.repo_full_name,
            pr_number=opened.pr_number,
            title=opened.title,
            body=opened.body,
            author=opened.author,
            base_branch=opened.base_branch,
            head_branch=opened.head_branch,
            diff_url=opened.diff_url,
            files_changed=opened.files_changed,
        ),
        PRCommented(
            meta=_meta(EventType.PR_COMMENTED),
            repo_full_name="Kimcheolhui/qaestro",
            pr_number=34,
            comment_id=123,
            author="Kimcheolhui",
            body="please review",
        ),
        PRReviewed(
            meta=_meta(EventType.PR_REVIEWED),
            repo_full_name="Kimcheolhui/qaestro",
            pr_number=34,
            reviewer="reviewer",
            state="commented",
            body="looks reasonable",
        ),
        CICompleted(
            meta=_meta(EventType.CI_COMPLETED),
            repo_full_name="Kimcheolhui/qaestro",
            pr_number=34,
            commit_sha="abc123",
            workflow_name="tests",
            conclusion="failure",
            run_url="https://github.com/Kimcheolhui/qaestro/actions/runs/1",
            failed_jobs=("pytest", "mypy"),
        ),
        ChatMention(
            meta=_meta(EventType.CHAT_MENTION),
            platform="discord",
            channel_id="channel-1",
            channel_name="qaestro",
            author="Kimcheolhui",
            message="@qaestro check this",
            thread_id="thread-1",
            referenced_pr=34,
        ),
    ]


def _stored_job_payload(redis: FakeRedis) -> dict[bytes, bytes]:
    fields = redis.added[-1][1]
    return {b"job": fields["job"].encode("utf-8")}


def _queue(redis: FakeRedis, *, busy_group_error: type[Exception] = Exception) -> RedisStreamsJobQueue:
    return RedisStreamsJobQueue(
        redis_client=redis,  # type: ignore[arg-type]
        stream="qaestro:jobs",
        group="qaestro-workers",
        consumer="worker-1",
        read_block_ms=0,
        claim_idle_ms=5000,
        busy_group_error=busy_group_error,
    )


def test_redis_streams_queue_ignores_existing_consumer_group_error() -> None:
    class BusyGroupError(Exception):
        pass

    redis = FakeRedis()
    redis.xgroup_create_error = BusyGroupError("BUSYGROUP Consumer Group name already exists")

    queue = _queue(redis, busy_group_error=BusyGroupError)

    assert isinstance(queue, RedisStreamsJobQueue)


def test_redis_streams_queue_reraises_unexpected_group_create_error() -> None:
    class BusyGroupError(Exception):
        pass

    redis = FakeRedis()
    redis.xgroup_create_error = BusyGroupError("connection refused")

    try:
        _queue(redis, busy_group_error=BusyGroupError)
        raise AssertionError("expected unexpected group creation errors to propagate")
    except BusyGroupError:
        pass


def test_redis_streams_queue_round_trips_all_event_job_types() -> None:
    for event in _events():
        redis = FakeRedis()
        queue = _queue(redis)
        original = EventJob(event=event, correlation_id=event.meta.correlation_id)

        queue.enqueue(original)
        redis.new_messages.append((b"1700000000000-0", _stored_job_payload(redis)))
        restored = queue.dequeue()

        assert redis.group_created == ("qaestro:jobs", "qaestro-workers", "0")
        assert restored == EventJob(
            event=original.event,
            correlation_id=event.meta.correlation_id,
            delivery_id="1700000000000-0",
        )


def test_redis_streams_queue_claims_pending_messages_before_reading_new_events() -> None:
    redis = FakeRedis()
    queue = _queue(redis)
    original = EventJob(event=_pr_opened(), correlation_id="corr-pr_opened")

    queue.enqueue(original)
    redis.claimed_messages.append((b"1700000000001-0", _stored_job_payload(redis)))
    restored = queue.dequeue()

    assert restored == EventJob(event=original.event, correlation_id="corr-pr_opened", delivery_id="1700000000001-0")


def test_redis_streams_queue_advances_pending_claim_cursor() -> None:
    redis = FakeRedis()
    queue = _queue(redis)
    original = EventJob(event=_pr_opened(), correlation_id="corr-pr_opened")

    queue.enqueue(original)
    redis.claimed_messages.append((b"1700000000001-0", _stored_job_payload(redis)))
    queue.dequeue()
    queue.dequeue()

    assert redis.claim_start_ids == ["0-0", "1700000000002-0"]


def test_redis_streams_queue_returns_malformed_job_for_bad_payload() -> None:
    redis = FakeRedis()
    queue = _queue(redis)

    redis.new_messages.append((b"1700000000003-0", {b"job": b"not-json"}))
    restored = queue.dequeue()

    assert isinstance(restored, MalformedEventJob)
    assert restored.delivery_id == "1700000000003-0"
    assert restored.error


def test_redis_streams_queue_returns_malformed_job_for_invalid_event_field_type() -> None:
    redis = FakeRedis()
    queue = _queue(redis)
    original = EventJob(event=_pr_opened(), correlation_id="corr-pr_opened")

    queue.enqueue(original)
    fields = _stored_job_payload(redis)
    payload = fields[b"job"].decode("utf-8").replace('"pr_number":34', '"pr_number":"not-an-int"')
    redis.new_messages.append((b"1700000000006-0", {b"job": payload.encode("utf-8")}))
    restored = queue.dequeue()

    assert isinstance(restored, MalformedEventJob)
    assert restored.delivery_id == "1700000000006-0"
    assert "pr_number" in restored.error


def test_redis_streams_queue_returns_malformed_job_for_wrong_json_shape() -> None:
    redis = FakeRedis()
    queue = _queue(redis)

    redis.new_messages.append((b"1700000000004-0", {b"job": b"[]"}))
    restored = queue.dequeue()

    assert isinstance(restored, MalformedEventJob)
    assert restored.delivery_id == "1700000000004-0"
    assert restored.error


def test_redis_streams_queue_acks_delivered_messages() -> None:
    redis = FakeRedis()
    queue = _queue(redis)

    queue.ack(EventJob(event=_pr_opened(), correlation_id="corr-pr_opened", delivery_id="1700000000000-0"))

    assert redis.acked == [("qaestro:jobs", "qaestro-workers", "1700000000000-0")]


def test_redis_streams_queue_ignores_ack_without_delivery_id() -> None:
    redis = FakeRedis()
    queue = _queue(redis)

    queue.ack(EventJob(event=_pr_opened(), correlation_id="corr-pr_opened"))

    assert redis.acked == []
