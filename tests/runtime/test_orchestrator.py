"""Tests for event orchestration and PR workflow sub-orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.adapters.renderers import PRCommentPayload
from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    ChatMention,
    CICompleted,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    ImpactArea,
    PRCommented,
    PREvent,
    PROpened,
    PRReviewed,
    RiskLevel,
    StrategyAction,
    StrategyResult,
    ValidationResult,
)
from src.runtime.orchestrator import (
    ChatWorkflowOrchestrator,
    CIWorkflowOrchestrator,
    EventOrchestrator,
    PRWorkflowDraft,
    PRWorkflowOrchestrator,
    PRWorkflowResult,
    UnsupportedEventError,
)


def _event_meta(event_id: str, event_type: EventType, correlation_id: str) -> EventMeta:
    return EventMeta(
        event_id=event_id,
        event_type=event_type,
        correlation_id=correlation_id,
        timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


def _pr_opened_event() -> PROpened:
    return PROpened(
        meta=_event_meta("evt-001", EventType.PR_OPENED, "corr-001"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=31,
        title="feat: add connector",
        body="Implements GitHub connector.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/connector",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/31.diff",
        files_changed=(
            FileChange(path="src/adapters/connectors/github/client.py", status="added", additions=120),
            FileChange(path="tests/adapters/connectors/test_github_client.py", status="added", additions=200),
        ),
    )


def _ci_completed_event() -> CICompleted:
    return CICompleted(
        meta=_event_meta("evt-ci-001", EventType.CI_COMPLETED, "corr-ci-001"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=31,
        commit_sha="abc123",
        workflow_name="Tests",
        conclusion="failure",
        run_url="https://github.com/Kimcheolhui/qaestro/actions/runs/1",
        failed_jobs=("pytest",),
    )


def _chat_mention_event() -> ChatMention:
    return ChatMention(
        meta=EventMeta(
            event_id="evt-chat-001",
            event_type=EventType.CHAT_MENTION,
            correlation_id="corr-chat-001",
            timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
            source=EventSource.SLACK,
        ),
        platform="slack",
        channel_id="C123",
        channel_name="qaestro",
        author="Kimcheolhui",
        message="@qaestro check PR 31",
        referenced_pr=31,
    )


def _pr_commented_event() -> PRCommented:
    return PRCommented(
        meta=_event_meta("evt-comment-001", EventType.PR_COMMENTED, "corr-comment-001"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=31,
        comment_id=1001,
        author="Kimcheolhui",
        body="Please check this PR.",
    )


def _pr_reviewed_event() -> PRReviewed:
    return PRReviewed(
        meta=_event_meta("evt-review-001", EventType.PR_REVIEWED, "corr-review-001"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=31,
        reviewer="Kimcheolhui",
        state="commented",
        body="Looks close.",
    )


def test_event_orchestrator_dispatches_pr_events_to_pr_sub_orchestrator():
    event = _pr_opened_event()
    orchestrator = EventOrchestrator()

    result = orchestrator.run(event)

    assert isinstance(result, PRWorkflowResult)
    assert result.event is event
    assert result.correlation_id == "corr-001"
    assert result.stage_order == ("context", "analyzer", "strategy", "validator", "renderer")
    assert result.comment_payload.repo_full_name == "Kimcheolhui/qaestro"
    assert result.comment_payload.pr_number == 31


def test_event_orchestrator_dispatches_ci_and_chat_to_stub_sub_orchestrators():
    ci_orchestrator = CIWorkflowOrchestrator()
    chat_orchestrator = ChatWorkflowOrchestrator()
    orchestrator = EventOrchestrator(
        ci_orchestrator=ci_orchestrator,
        chat_orchestrator=chat_orchestrator,
    )

    with pytest.raises(UnsupportedEventError, match="CI workflow orchestration is planned"):
        orchestrator.run(_ci_completed_event())

    with pytest.raises(UnsupportedEventError, match="Chat workflow orchestration is planned"):
        orchestrator.run(_chat_mention_event())


def test_event_orchestrator_routes_pr_comment_and_review_events_to_explicit_stubs():
    orchestrator = EventOrchestrator()

    with pytest.raises(UnsupportedEventError, match="PR comment workflow orchestration is planned"):
        orchestrator.run(_pr_commented_event())

    with pytest.raises(UnsupportedEventError, match="PR review workflow orchestration is planned"):
        orchestrator.run(_pr_reviewed_event())


def test_pr_workflow_orchestrator_runs_stub_flow_and_renders_pr_comment_payload():
    event = _pr_opened_event()
    orchestrator = PRWorkflowOrchestrator()

    result = orchestrator.run(event)

    assert isinstance(result, PRWorkflowResult)
    assert result.event is event
    assert result.correlation_id == "corr-001"
    assert result.stage_order == ("context", "analyzer", "strategy", "validator", "renderer")
    assert result.impact.summary.startswith("PR #31 (feat: add connector) changes 2 files")
    assert result.strategy.reasoning.startswith("High risk")
    assert len(result.validations) == 3
    assert result.comment_payload.repo_full_name == "Kimcheolhui/qaestro"
    assert result.comment_payload.pr_number == 31
    assert "feat: add connector" in result.comment_payload.body
    assert "corr-001" in result.comment_payload.body


def test_pr_workflow_orchestrator_passes_draft_to_injected_renderer():
    class RecordingRenderer:
        def __init__(self) -> None:
            self.calls: list[PRWorkflowDraft] = []

        def render(self, draft: PRWorkflowDraft) -> PRCommentPayload:
            self.calls.append(draft)
            return PRCommentPayload(
                repo_full_name=draft.event.repo_full_name,
                pr_number=draft.event.pr_number,
                body="custom renderer output",
            )

    renderer = RecordingRenderer()
    orchestrator = PRWorkflowOrchestrator(renderer=renderer)

    result = orchestrator.run(_pr_opened_event())

    assert len(renderer.calls) == 1
    assert renderer.calls[0].event is result.event
    assert renderer.calls[0].report == result.report
    assert renderer.calls[0].correlation_id == result.correlation_id
    assert not hasattr(renderer.calls[0], "comment_payload")
    assert result.comment_payload.body == "custom renderer output"


def test_pr_workflow_orchestrator_can_skip_validation_via_policy_hook():
    orchestrator = PRWorkflowOrchestrator(should_validate=lambda event, impact, strategy: False)

    result = orchestrator.run(_pr_opened_event())

    assert result.validations == ()
    assert result.stage_order == ("context", "analyzer", "strategy", "renderer")
    assert "Validation not executed" in result.comment_payload.body


def test_pr_workflow_orchestrator_accepts_replaceable_components():
    class RecordingAnalyzer:
        def __init__(self) -> None:
            self.events: list[PREvent] = []

        def analyze(self, context: object) -> BehaviourImpact:
            self.events.append(context)  # type: ignore[arg-type]
            return BehaviourImpact(
                summary="custom impact",
                areas=(
                    ImpactArea(
                        module="custom/module",
                        description="custom analyzer output",
                        risk_level=RiskLevel.HIGH,
                    ),
                ),
                overall_risk=RiskLevel.HIGH,
            )

    class RecordingStrategyEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str, BehaviourImpact]] = []

        def plan(
            self,
            *,
            repo_full_name: str,
            pr_number: int,
            title: str,
            impact: BehaviourImpact,
        ) -> StrategyResult:
            self.calls.append((repo_full_name, pr_number, title, impact))
            return StrategyResult(
                actions=(
                    StrategyAction(
                        action_type=ActionType.CUSTOM,
                        description="custom action",
                        target="custom-target",
                    ),
                ),
                reasoning="custom strategy",
                confidence=0.9,
            )

    class RecordingValidator:
        def __init__(self) -> None:
            self.calls: list[StrategyResult] = []

        def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
            self.calls.append(strategy)
            return ()

    analyzer = RecordingAnalyzer()
    strategy_engine = RecordingStrategyEngine()
    validator = RecordingValidator()
    event = _pr_opened_event()
    orchestrator = PRWorkflowOrchestrator(
        analyzer=analyzer,
        strategy_engine=strategy_engine,
        validator=validator,
    )

    result = orchestrator.run(event)

    assert analyzer.events[0].repo_full_name == event.repo_full_name
    assert strategy_engine.calls == [(event.repo_full_name, event.pr_number, event.title, result.impact)]
    assert validator.calls == [result.strategy]
    assert result.impact.summary == "custom impact"
    assert result.strategy.reasoning == "custom strategy"
    assert result.stage_order == ("context", "analyzer", "strategy", "validator", "renderer")
