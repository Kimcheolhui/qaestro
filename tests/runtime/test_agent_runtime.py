"""Tests for provider-neutral Agent Runtime runner contracts."""

from __future__ import annotations

from src.runtime.agent import (
    AgentRunInput,
    AgentRunStatus,
    AgentSessionScope,
    FakeAgentRunner,
    WorkflowAgentSessionManager,
)
from src.runtime.stages import WorkflowStage
from src.runtime.tools import AgentFrameworkToolSpec, ToolCapability


def test_fake_runner_creates_workflow_scoped_session_and_records_stage_turns() -> None:
    manager = WorkflowAgentSessionManager(runner=FakeAgentRunner(response="analysis ok"))
    session = manager.start_workflow_session(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=42,
        head_sha="abc123",
        trigger="manual",
        correlation_id="corr-session",
    )

    result = manager.run_stage(
        session.handle,
        AgentRunInput(
            stage=WorkflowStage.ANALYZER,
            prompt="Analyze this PR",
            correlation_id="corr-session",
            allowed_tools=(
                AgentFrameworkToolSpec(
                    name="github.pr.diff",
                    description="Read PR diff",
                    parameters_schema={"type": "object", "properties": {}},
                    stage=WorkflowStage.ANALYZER,
                    capabilities=(ToolCapability.READ,),
                ),
            ),
            max_turns=2,
            max_tool_calls=3,
            timeout_seconds=30.0,
        ),
    )

    assert session.handle.scope is AgentSessionScope.WORKFLOW
    assert session.handle.repo_full_name == "Kimcheolhui/qaestro"
    assert session.handle.pr_number == 42
    assert session.handle.head_sha == "abc123"
    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.output_text == "analysis ok"
    assert result.stage is WorkflowStage.ANALYZER
    assert result.allowed_tool_names == ("github.pr.diff",)
    assert manager.turns_for_session(session.handle.session_id)[0].stage is WorkflowStage.ANALYZER


def test_session_manager_reuses_workflow_session_without_widening_stage_tools() -> None:
    manager = WorkflowAgentSessionManager(runner=FakeAgentRunner(response="ok"))
    session = manager.start_workflow_session(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=42,
        head_sha="abc123",
        trigger="manual",
        correlation_id="corr-session",
    )

    manager.run_stage(
        session.handle,
        AgentRunInput(
            stage=WorkflowStage.ANALYZER,
            prompt="Analyze",
            correlation_id="corr-session",
            allowed_tools=(
                AgentFrameworkToolSpec(
                    name="github.pr.diff",
                    description="Read PR diff",
                    parameters_schema={"type": "object", "properties": {}},
                    stage=WorkflowStage.ANALYZER,
                    capabilities=(ToolCapability.READ,),
                ),
            ),
        ),
    )
    manager.run_stage(
        session.handle,
        AgentRunInput(
            stage=WorkflowStage.VALIDATOR,
            prompt="Validate",
            correlation_id="corr-session",
            allowed_tools=(),
        ),
    )

    turns = manager.turns_for_session(session.handle.session_id)
    assert [turn.stage for turn in turns] == [WorkflowStage.ANALYZER, WorkflowStage.VALIDATOR]
    assert turns[0].allowed_tool_names == ("github.pr.diff",)
    assert turns[1].allowed_tool_names == ()


def test_session_manager_cancels_superseded_head_and_closes_pr_sessions() -> None:
    manager = WorkflowAgentSessionManager(runner=FakeAgentRunner(response="ok"))
    old = manager.start_workflow_session(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=42,
        head_sha="old-sha",
        trigger="manual",
        correlation_id="corr-old",
    )
    current = manager.start_workflow_session(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=42,
        head_sha="new-sha",
        trigger="manual",
        correlation_id="corr-new",
    )

    cancelled = manager.cancel_superseded_sessions(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=42,
        current_head_sha="new-sha",
        reason="new commit pushed",
    )

    assert [session.handle.session_id for session in cancelled] == [old.handle.session_id]
    assert manager.get_session(old.handle.session_id).is_active is False
    assert manager.get_session(old.handle.session_id).termination_reason == "new commit pushed"
    assert manager.get_session(current.handle.session_id).is_active is True

    closed = manager.close_pr_sessions(repo_full_name="Kimcheolhui/qaestro", pr_number=42, reason="PR merged")

    assert {session.handle.session_id for session in closed} == {current.handle.session_id}
    assert manager.get_session(current.handle.session_id).is_active is False
    assert manager.get_session(current.handle.session_id).termination_reason == "PR merged"
