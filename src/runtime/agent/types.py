"""Provider-neutral Agent Runtime value contracts.

This module intentionally contains no Microsoft Agent Framework or provider SDK
objects. It models qaestro's own execution contract so workflow/orchestrator code
can reason about session scope, stage boundaries, and cleanup without depending
on a concrete LLM backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from src.runtime.stages import WorkflowStage
from src.runtime.tools import AgentFrameworkToolSpec


class AgentSessionScope(StrEnum):
    """Supported live session scopes for Agent Runtime execution."""

    WORKFLOW = "workflow"
    STAGE = "stage"


class AgentSessionStatus(StrEnum):
    """Lifecycle state of a live provider-neutral agent session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AgentRunStatus(StrEnum):
    """Normalized status for one stage turn executed through an agent runner."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentSessionHandle:
    """Opaque provider-neutral reference to a live workflow/stage session."""

    session_id: str
    scope: AgentSessionScope
    repo_full_name: str
    pr_number: int
    head_sha: str
    trigger: str
    correlation_id: str
    provider_session_id: str = ""


@dataclass(frozen=True)
class AgentRunInput:
    """One stage turn request sent to an Agent Runtime runner.

    ``allowed_tools`` must be supplied per turn so reusing a workflow-scoped
    session never widens a later stage's tool access implicitly.
    """

    stage: WorkflowStage
    prompt: str
    correlation_id: str
    allowed_tools: tuple[AgentFrameworkToolSpec, ...] = ()
    context: Mapping[str, object] | None = None
    max_turns: int | None = None
    max_tool_calls: int | None = None
    timeout_seconds: float | None = None

    @property
    def allowed_tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.allowed_tools)


@dataclass(frozen=True)
class AgentRunResult:
    """Provider-neutral result returned by an Agent Runtime runner."""

    session: AgentSessionHandle
    stage: WorkflowStage
    status: AgentRunStatus
    output_text: str = ""
    error: str = ""
    allowed_tool_names: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is AgentRunStatus.SUCCEEDED


@dataclass(frozen=True)
class AgentSessionTurn:
    """Redacted audit metadata for one stage turn inside a session."""

    stage: WorkflowStage
    correlation_id: str
    status: AgentRunStatus
    allowed_tool_names: tuple[str, ...]
    error: str = ""


@dataclass(frozen=True)
class AgentSessionRecord:
    """In-memory lifecycle record for one provider-neutral agent session."""

    handle: AgentSessionHandle
    status: AgentSessionStatus
    turns: tuple[AgentSessionTurn, ...] = ()
    termination_reason: str = ""

    @property
    def is_active(self) -> bool:
        return self.status is AgentSessionStatus.ACTIVE


class AgentRunner(Protocol):
    """Provider-neutral runner implemented by fake and real provider adapters."""

    def start_session(self, handle: AgentSessionHandle) -> AgentSessionHandle: ...

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult: ...

    def close_session(self, handle: AgentSessionHandle, *, reason: str) -> None: ...
