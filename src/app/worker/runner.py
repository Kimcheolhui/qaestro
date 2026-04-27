"""Background worker execution loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Protocol

from src.adapters.renderers import PRCommentPayload
from src.core.contracts import Event
from src.runtime.orchestrator import EventOrchestrator, PRWorkflowResult
from src.shared import get_logger

from ..jobs import EventJob, JobQueue, MalformedEventJob, QueuedJob
from .types import WorkerExecution, WorkerExecutionContext, WorkerStatus

logger = get_logger(__name__)


class Orchestrator(Protocol):
    """Minimal orchestrator surface required by the worker."""

    def run(self, event: Event) -> PRWorkflowResult: ...


class OutputPoster(Protocol):
    """Posts rendered PR workflow output to an external system."""

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> object: ...


class NoopOutputPoster:
    """Default output tool adapter used for side-effect-free local runs.

    This placeholder intentionally performs no external write. Durable worker
    modes must inject a ToolRuntime-backed poster so output writes pass through
    stage policy and audit.
    """

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> object:
        return None


class Worker:
    """Execute normalized event jobs through the orchestrator and output poster."""

    def __init__(
        self,
        *,
        orchestrator: Orchestrator | None = None,
        output_poster: OutputPoster | None = None,
        max_attempts: int = 3,
        timeout_seconds: float | None = None,
        agent_runner: object | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._orchestrator = orchestrator or EventOrchestrator()
        self._output_poster = output_poster or NoopOutputPoster()
        self._max_attempts = max_attempts
        self._timeout_seconds = timeout_seconds
        self._agent_runner = agent_runner

    def process(self, job: QueuedJob) -> WorkerExecution:
        if isinstance(job, MalformedEventJob):
            return WorkerExecution(
                correlation_id="",
                status=WorkerStatus.FAILED,
                attempts=0,
                error=f"malformed queue message {job.delivery_id}: {job.error}",
            )

        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            context = WorkerExecutionContext(
                correlation_id=job.correlation_id,
                attempt=attempt,
                max_attempts=self._max_attempts,
                timeout_seconds=self._timeout_seconds,
                agent_runner=self._agent_runner,
            )
            try:
                result = self._run_once(job, context)
            except Exception as exc:
                last_error = str(exc)
                if attempt == self._max_attempts:
                    return WorkerExecution(
                        correlation_id=job.correlation_id,
                        status=WorkerStatus.FAILED,
                        attempts=attempt,
                        error=last_error,
                    )
                continue

            return WorkerExecution(
                correlation_id=job.correlation_id,
                status=WorkerStatus.SUCCEEDED,
                attempts=attempt,
                result=result,
            )

        return WorkerExecution(
            correlation_id=job.correlation_id,
            status=WorkerStatus.FAILED,
            attempts=self._max_attempts,
            error=last_error,
        )

    def run_until_empty(self, queue: JobQueue) -> tuple[WorkerExecution, ...]:
        results: list[WorkerExecution] = []
        while (job := queue.dequeue()) is not None:
            execution = self.process(job)
            results.append(execution)
            queue.ack(job)
        return tuple(results)

    def run_forever(self, queue: JobQueue, *, idle_sleep_seconds: float = 0.1) -> None:
        """Continuously process jobs from a blocking queue.

        Redis-backed queues block in ``dequeue()``. The small idle sleep keeps
        accidental non-blocking queue usage from turning into a CPU busy loop.
        """
        while True:
            if (job := queue.dequeue()) is None:
                time.sleep(idle_sleep_seconds)
                continue
            execution = self.process(job)
            if execution.status is WorkerStatus.FAILED:
                self._log_failed_execution(job, execution)
                queue.ack(job)
                # Step 2 records terminal failures and acknowledges them so one
                # poison job does not block the shared stream forever. A DLQ and
                # metrics are planned for later operational hardening.
                continue
            queue.ack(job)

    def _log_failed_execution(self, job: QueuedJob, execution: WorkerExecution) -> None:
        delivery_id = job.delivery_id
        correlation_id = execution.correlation_id
        job_type = type(job).__name__
        if isinstance(job, EventJob):
            correlation_id = correlation_id or job.correlation_id
            job_type = job.event.meta.event_type.value

        logger.error(
            "worker job failed",
            extra={
                "correlation_id": correlation_id,
                "delivery_id": delivery_id,
                "attempts": execution.attempts,
                "error": execution.error,
                "job_type": job_type,
            },
        )

    def _run_once(self, job: EventJob, context: WorkerExecutionContext) -> PRWorkflowResult:
        if context.timeout_seconds is not None:
            # Timeout currently guards orchestrator execution. Posting remains
            # synchronous so the Step 2 worker has a real timeout failure state
            # without pretending to provide durable cancellation for all I/O yet.
            result = _run_with_timeout(
                lambda: self._orchestrator.run(job.event),
                timeout_seconds=context.timeout_seconds,
            )
            self._output_poster.post_comment(result.comment_payload, correlation_id=job.correlation_id)
            return result
        return self._run_pipeline(job, context)

    def _run_pipeline(self, job: EventJob, context: WorkerExecutionContext) -> PRWorkflowResult:
        # ``context`` is built here so Step 2 fixes the extension seam for
        # Agent Framework integration, even though no runner is invoked until
        # later milestones.
        _ = context.agent_runner
        result = self._orchestrator.run(job.event)
        self._output_poster.post_comment(result.comment_payload, correlation_id=job.correlation_id)
        return result


def _run_with_timeout(operation: Callable[[], PRWorkflowResult], *, timeout_seconds: float) -> PRWorkflowResult:
    """Run one worker attempt with a basic timeout guard.

    This deliberately uses a one-shot executor instead of durable cancellation.
    It gives Step 2 a real timeout failure state; cooperative cancellation and
    process-level isolation remain deployment concerns for the future runner.
    """

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(operation)
    timed_out = False
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        timed_out = True
        future.cancel()
        raise TimeoutError(f"worker attempt timed out after {timeout_seconds:g}s") from exc
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=timed_out)
