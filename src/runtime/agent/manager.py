"""Workflow-scoped Agent Runtime session manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from src.runtime.agent.types import (
    AgentRunInput,
    AgentRunner,
    AgentRunResult,
    AgentSessionHandle,
    AgentSessionRecord,
    AgentSessionScope,
    AgentSessionStatus,
    AgentSessionTurn,
)


class AgentSessionNotFoundError(RuntimeError):
    """Raised when a session handle does not match a known live/retained record."""


class WorkflowAgentSessionManager:
    """Manage workflow-scoped Agent Runtime sessions.

    The manager treats provider sessions as live execution handles, not as durable
    source-of-truth state. It retains only normalized turn metadata in memory for
    tests and future audit stores. Stage turns always provide their own allowed
    tools so a reused workflow session cannot silently inherit broader access.
    """

    def __init__(self, *, runner: AgentRunner) -> None:
        self._runner = runner
        self._records: dict[str, AgentSessionRecord] = {}
        self._next_id = 1

    def start_workflow_session(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        trigger: str,
        correlation_id: str,
    ) -> AgentSessionRecord:
        session_id = self._new_session_id(repo_full_name=repo_full_name, pr_number=pr_number, head_sha=head_sha)
        handle = AgentSessionHandle(
            session_id=session_id,
            scope=AgentSessionScope.WORKFLOW,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            trigger=trigger,
            correlation_id=correlation_id,
        )
        handle = self._runner.start_session(handle)
        record = AgentSessionRecord(handle=handle, status=AgentSessionStatus.ACTIVE)
        self._records[handle.session_id] = record
        return record

    def run_stage(self, handle: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        record = self.get_session(handle.session_id)
        if not record.is_active:
            msg = f"agent session {handle.session_id!r} is not active"
            raise AgentSessionNotFoundError(msg)
        result = self._runner.run(session=record.handle, run_input=run_input)
        turn = AgentSessionTurn(
            stage=run_input.stage,
            correlation_id=run_input.correlation_id,
            status=result.status,
            allowed_tool_names=run_input.allowed_tool_names,
            error=result.error,
        )
        self._records[handle.session_id] = replace(record, turns=(*record.turns, turn))
        return result

    def get_session(self, session_id: str) -> AgentSessionRecord:
        record = self._records.get(session_id)
        if record is None:
            msg = f"agent session {session_id!r} was not found"
            raise AgentSessionNotFoundError(msg)
        return record

    def turns_for_session(self, session_id: str) -> tuple[AgentSessionTurn, ...]:
        return self.get_session(session_id).turns

    def cancel_superseded_sessions(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        current_head_sha: str,
        reason: str,
    ) -> tuple[AgentSessionRecord, ...]:
        return self._close_matching(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            reason=reason,
            predicate=lambda record: record.handle.head_sha != current_head_sha,
            terminal_status=AgentSessionStatus.CANCELLED,
        )

    def close_pr_sessions(self, *, repo_full_name: str, pr_number: int, reason: str) -> tuple[AgentSessionRecord, ...]:
        return self._close_matching(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            reason=reason,
            predicate=lambda record: True,
            terminal_status=AgentSessionStatus.COMPLETED,
        )

    def _close_matching(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        reason: str,
        predicate: Callable[[AgentSessionRecord], bool],
        terminal_status: AgentSessionStatus,
    ) -> tuple[AgentSessionRecord, ...]:
        closed: list[AgentSessionRecord] = []
        for record in tuple(self._records.values()):
            if not record.is_active:
                continue
            if record.handle.repo_full_name != repo_full_name or record.handle.pr_number != pr_number:
                continue
            if not predicate(record):
                continue
            self._runner.close_session(record.handle, reason=reason)
            updated = replace(record, status=terminal_status, termination_reason=reason)
            self._records[record.handle.session_id] = updated
            closed.append(updated)
        return tuple(closed)

    def _new_session_id(self, *, repo_full_name: str, pr_number: int, head_sha: str) -> str:
        safe_repo = repo_full_name.replace("/", "-")
        short_sha = head_sha[:12] if head_sha else "unknown"
        session_id = f"review-{safe_repo}-{pr_number}-{short_sha}-{self._next_id}"
        self._next_id += 1
        return session_id
