"""Tests for background worker job execution."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from src.adapters.renderers import PRCommentPayload
from src.app.worker import EventJob, InMemoryJobQueue, MalformedEventJob, Worker, WorkerStatus
from src.core.contracts import Event, EventMeta, EventSource, EventType, PROpened
from src.runtime.orchestrator import PRWorkflowResult


def _event() -> PROpened:
    return PROpened(
        meta=EventMeta(
            event_id="evt-worker-001",
            event_type=EventType.PR_OPENED,
            correlation_id="corr-worker-001",
            timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
            source=EventSource.GITHUB,
        ),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=32,
        title="feat: worker",
        body="",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/worker",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/32.diff",
    )


class RecordingOrchestrator:
    def __init__(self, result: PRWorkflowResult) -> None:
        self.events: list[PROpened] = []
        self._result = result

    def run(self, event: Event) -> PRWorkflowResult:
        assert isinstance(event, PROpened)
        self.events.append(event)
        return self._result


class RecordingCommentPoster:
    def __init__(self) -> None:
        self.payloads: list[PRCommentPayload] = []

    def post_comment(self, payload: PRCommentPayload) -> None:
        self.payloads.append(payload)


def _result(event: PROpened) -> PRWorkflowResult:
    payload = PRCommentPayload(
        repo_full_name=event.repo_full_name,
        pr_number=event.pr_number,
        body="worker output",
    )
    # The worker only needs the event and rendered payload. The report is kept
    # opaque here because report construction belongs to the orchestrator.
    return PRWorkflowResult(
        event=event,
        report=object(),  # type: ignore[arg-type]
        comment_payload=payload,
        stage_order=("analyzer", "strategy", "renderer"),
    )


def test_worker_processes_single_event_and_posts_comment() -> None:
    event = _event()
    orchestrator = RecordingOrchestrator(_result(event))
    poster = RecordingCommentPoster()
    worker = Worker(orchestrator=orchestrator, comment_poster=poster)

    result = worker.process(EventJob(event=event, correlation_id=event.meta.correlation_id))

    assert result.status == WorkerStatus.SUCCEEDED
    assert result.correlation_id == "corr-worker-001"
    assert orchestrator.events == [event]
    assert poster.payloads == [orchestrator._result.comment_payload]


def test_worker_retries_transient_failure_and_reports_attempt_count() -> None:
    event = _event()
    result = _result(event)

    class FlakyOrchestrator:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, event: Event) -> PRWorkflowResult:
            assert isinstance(event, PROpened)
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return result

    orchestrator = FlakyOrchestrator()
    poster = RecordingCommentPoster()
    worker = Worker(orchestrator=orchestrator, comment_poster=poster, max_attempts=2)

    execution = worker.process(EventJob(event=event, correlation_id=event.meta.correlation_id))

    assert execution.status == WorkerStatus.SUCCEEDED
    assert execution.attempts == 2
    assert poster.payloads == [result.comment_payload]


def test_worker_reports_failure_after_retries_exhausted() -> None:
    event = _event()

    class FailingOrchestrator:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, event: Event) -> PRWorkflowResult:
            assert isinstance(event, PROpened)
            self.calls += 1
            raise RuntimeError("boom")

    orchestrator = FailingOrchestrator()
    poster = RecordingCommentPoster()
    worker = Worker(orchestrator=orchestrator, comment_poster=poster, max_attempts=2)

    execution = worker.process(EventJob(event=event, correlation_id=event.meta.correlation_id))

    assert execution.status == WorkerStatus.FAILED
    assert execution.attempts == 2
    assert execution.error == "boom"
    assert poster.payloads == []


def test_worker_enforces_timeout_per_attempt() -> None:
    event = _event()

    class SlowOrchestrator:
        def run(self, event: Event) -> PRWorkflowResult:
            assert isinstance(event, PROpened)
            time.sleep(0.05)
            return _result(event)

    poster = RecordingCommentPoster()
    worker = Worker(orchestrator=SlowOrchestrator(), comment_poster=poster, max_attempts=1, timeout_seconds=0.01)

    start = time.monotonic()
    execution = worker.process(EventJob(event=event, correlation_id=event.meta.correlation_id))
    elapsed = time.monotonic() - start

    assert execution.status == WorkerStatus.FAILED
    assert execution.attempts == 1
    assert "timed out" in execution.error
    assert elapsed < 0.04
    assert poster.payloads == []


def test_worker_acks_successful_queue_jobs() -> None:
    event = _event()
    job = EventJob(event=event, correlation_id="acked")

    class AckRecordingQueue(InMemoryJobQueue):
        def __init__(self) -> None:
            super().__init__([job])
            self.acked: list[EventJob] = []

        def ack(self, job: EventJob | MalformedEventJob) -> None:
            assert isinstance(job, EventJob)
            self.acked.append(job)

    queue = AckRecordingQueue()
    worker = Worker(comment_poster=RecordingCommentPoster())

    executions = worker.run_until_empty(queue)

    assert executions[0].status == WorkerStatus.SUCCEEDED
    assert queue.acked == [job]


def test_worker_acks_failed_queue_jobs_after_retries_are_exhausted() -> None:
    event = _event()
    job = EventJob(event=event, correlation_id="failed")

    class FailingOrchestrator:
        def run(self, event: Event) -> PRWorkflowResult:
            raise RuntimeError("terminal failure")

    class AckRecordingQueue(InMemoryJobQueue):
        def __init__(self) -> None:
            super().__init__([job])
            self.acked: list[EventJob] = []

        def ack(self, job: EventJob | MalformedEventJob) -> None:
            assert isinstance(job, EventJob)
            self.acked.append(job)

    queue = AckRecordingQueue()
    worker = Worker(orchestrator=FailingOrchestrator(), max_attempts=1)

    executions = worker.run_until_empty(queue)

    assert executions[0].status == WorkerStatus.FAILED
    assert queue.acked == [job]


def test_worker_run_forever_sleeps_when_queue_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyThenStopQueue:
        def __init__(self) -> None:
            self.dequeue_calls = 0

        def enqueue(self, job: EventJob) -> None:
            raise AssertionError("not used")

        def dequeue(self) -> EventJob | None:
            self.dequeue_calls += 1
            if self.dequeue_calls == 1:
                return None
            raise KeyboardInterrupt

        def ack(self, job: EventJob | MalformedEventJob) -> None:
            raise AssertionError("not used")

    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("src.app.worker.runner.time.sleep", record_sleep)
    worker = Worker()

    try:
        worker.run_forever(EmptyThenStopQueue(), idle_sleep_seconds=0.25)
        raise AssertionError("expected test queue to stop the loop")
    except KeyboardInterrupt:
        pass

    assert sleeps == [0.25]


def test_worker_acks_malformed_queue_jobs() -> None:
    job = MalformedEventJob(delivery_id="1700000000003-0", error="bad json")

    class AckRecordingQueue:
        def __init__(self) -> None:
            self._jobs = [job]
            self.acked: list[MalformedEventJob] = []

        def enqueue(self, job: EventJob) -> None:
            raise AssertionError("not used")

        def dequeue(self) -> MalformedEventJob | None:
            if not self._jobs:
                return None
            return self._jobs.pop(0)

        def ack(self, job: EventJob | MalformedEventJob) -> None:
            assert isinstance(job, MalformedEventJob)
            self.acked.append(job)

    queue = AckRecordingQueue()
    worker = Worker()

    executions = worker.run_until_empty(queue)

    assert executions[0].status == WorkerStatus.FAILED
    assert "malformed queue message" in executions[0].error
    assert queue.acked == [job]


def test_queue_runs_until_empty_in_fifo_order() -> None:
    first = EventJob(event=_event(), correlation_id="first")
    second = EventJob(event=_event(), correlation_id="second")
    queue = InMemoryJobQueue([first, second])

    assert queue.dequeue() is first
    assert queue.dequeue() is second
    assert queue.dequeue() is None
