"""Tests for closed workflow stage contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from src.adapters.renderers import PRCommentPayload
from src.core.contracts import EventMeta, EventSource, EventType, FileChange, PROpened
from src.runtime.orchestrator import PRWorkflowDraft, PRWorkflowOrchestrator
from src.runtime.stages import WorkflowStage
from src.runtime.tools import RegisteredToolRuntime, StageToolPolicy, ToolCall, ToolCapability, ToolDefinition


def _pr_opened_event() -> PROpened:
    return PROpened(
        meta=EventMeta(
            event_id="evt-stage-001",
            event_type=EventType.PR_OPENED,
            correlation_id="corr-stage-001",
            timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=UTC),
            source=EventSource.GITHUB,
        ),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=31,
        title="feat: stage enum",
        body="Implements workflow stages.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/stage-enum",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/31.diff",
        files_changed=(
            FileChange(path="src/runtime/stages.py", status="added", additions=20),
            FileChange(path="src/runtime/orchestrator/pr_workflow.py", status="modified", additions=5),
        ),
    )


def test_workflow_stage_enum_defines_runtime_stage_values() -> None:
    assert issubclass(WorkflowStage, StrEnum)
    assert tuple(stage.value for stage in WorkflowStage) == (
        "context",
        "analyzer",
        "strategy",
        "validator",
        "renderer",
        "output",
    )


def test_pr_workflow_reports_closed_stage_enum_order() -> None:
    renderer_drafts: list[PRWorkflowDraft] = []

    class RecordingRenderer:
        def render(self, draft: PRWorkflowDraft) -> PRCommentPayload:
            renderer_drafts.append(draft)
            return PRCommentPayload(
                repo_full_name=draft.event.repo_full_name,
                pr_number=draft.event.pr_number,
                body="stage enum output",
            )

    result = PRWorkflowOrchestrator(renderer=RecordingRenderer()).run(_pr_opened_event())

    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.VALIDATOR,
        WorkflowStage.RENDERER,
    )
    assert renderer_drafts[0].stage_order == result.stage_order


def test_tool_runtime_policy_and_audit_use_workflow_stage_enum() -> None:
    runtime = RegisteredToolRuntime(
        tools=(
            ToolDefinition(
                name="demo.read",
                capabilities=(ToolCapability.READ,),
                handler=lambda call: {"stage": call.stage},
            ),
        ),
        policy=StageToolPolicy({WorkflowStage.CONTEXT: ("demo.read",)}),
    )

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="demo.read",
            input={},
            correlation_id="corr-stage-enum",
        )
    )

    assert result.ok is True
    assert result.output == {"stage": WorkflowStage.CONTEXT}
    assert runtime.audit_log[0].stage is WorkflowStage.CONTEXT
