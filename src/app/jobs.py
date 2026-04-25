"""Shared application job contracts used by gateway and worker."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from src.core.contracts import Event


@dataclass(frozen=True)
class EventJob:
    """Retryable worker input created from a normalized event.

    The gateway stores normalized events in this small envelope so retry logic
    can preserve correlation id and event metadata without depending on raw
    provider payloads.
    """

    event: Event
    correlation_id: str


class EnqueueQueue(Protocol):
    """Minimal enqueue-only queue surface required by the gateway."""

    def enqueue(self, job: EventJob) -> None: ...


class JobQueue(EnqueueQueue, Protocol):
    """Queue contract shared by gateway and worker.

    The in-memory implementation below is deliberately simple. Durable queue
    providers can replace it later as long as they preserve this enqueue/dequeue
    contract.
    """

    def dequeue(self) -> EventJob | None: ...


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

    def __len__(self) -> int:
        return len(self._jobs)
