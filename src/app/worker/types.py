"""Worker job and execution result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
from typing import Any

from src.runtime.orchestrator import CIWorkflowResult, PRWorkflowResult


@unique
class WorkerStatus(Enum):
    """Terminal state of one worker job execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Per-job execution context passed through worker internals.

    ``agent_runner`` is intentionally opaque in Step 2. It is the extension slot
    where the Microsoft Agent Framework runner can be attached later without
    changing the queue/job contract.
    """

    correlation_id: str
    attempt: int
    max_attempts: int
    timeout_seconds: float | None = None
    agent_runner: Any | None = None


@dataclass(frozen=True)
class WorkerExecution:
    """Result of processing one :class:`EventJob`."""

    correlation_id: str
    status: WorkerStatus
    attempts: int
    result: PRWorkflowResult | CIWorkflowResult | None = None
    error: str = ""
