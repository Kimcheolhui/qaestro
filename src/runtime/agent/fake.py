"""Deterministic fake Agent Runtime runner for tests and local wiring."""

from __future__ import annotations

from src.runtime.agent.types import AgentRunInput, AgentRunner, AgentRunResult, AgentRunStatus, AgentSessionHandle


class FakeAgentRunner(AgentRunner):
    """Small fake runner that exercises the provider-neutral contract.

    The fake deliberately performs no LLM call. It lets config, session lifecycle,
    stage tool exposure, and worker/orchestrator wiring tests run without real
    provider credentials.
    """

    def __init__(self, *, response: str = "") -> None:
        self._response = response
        self.started_sessions: list[AgentSessionHandle] = []
        self.closed_sessions: list[tuple[str, str]] = []
        self.run_inputs: list[AgentRunInput] = []

    def start_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        self.started_sessions.append(handle)
        return handle

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        self.run_inputs.append(run_input)
        return AgentRunResult(
            session=session,
            stage=run_input.stage,
            status=AgentRunStatus.SUCCEEDED,
            output_text=self._response,
            allowed_tool_names=run_input.allowed_tool_names,
        )

    def close_session(self, handle: AgentSessionHandle, *, reason: str) -> None:
        self.closed_sessions.append((handle.session_id, reason))
