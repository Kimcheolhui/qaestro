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
    PRWorkflowDepth,
    PRWorkflowDraft,
    PRWorkflowOrchestrator,
    PRWorkflowResult,
    PRWorkflowTriage,
    RuleBasedPRWorkflowTriageClassifier,
    UnsupportedEventError,
)
from src.runtime.stages import WorkflowStage


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
    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.TRIAGE,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.VALIDATOR,
        WorkflowStage.RENDERER,
    )
    assert result.comment_payload is not None
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
    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.TRIAGE,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.VALIDATOR,
        WorkflowStage.RENDERER,
    )
    assert result.impact.summary.startswith("PR #31 (feat: add connector) changes 2 files")
    assert result.strategy.reasoning.startswith("High risk")
    assert len(result.validations) == 3
    assert result.comment_payload is not None
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
    assert renderer.calls[0].triage == result.triage
    assert renderer.calls[0].correlation_id == result.correlation_id
    assert not hasattr(renderer.calls[0], "comment_payload")
    assert result.comment_payload is not None
    assert result.comment_payload.body == "custom renderer output"


def test_pr_workflow_orchestrator_can_skip_validation_via_policy_hook():
    normal_triage = PRWorkflowTriage(
        depth=PRWorkflowDepth.NORMAL,
        rationale="Normal analysis can still skip validation by policy.",
        allowed_stages=(WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR),
    )
    orchestrator = PRWorkflowOrchestrator(
        triage_classifier=lambda context: normal_triage,
        should_validate=lambda event, impact, strategy: False,
    )

    result = orchestrator.run(_pr_opened_event())

    assert result.validations == ()
    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.TRIAGE,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.RENDERER,
    )
    assert result.comment_payload is not None
    assert "Validation not executed" in result.comment_payload.body


def test_pr_workflow_orchestrator_can_emit_lightweight_triage_output_without_full_analysis() -> None:
    event = PROpened(
        meta=_event_meta("evt-docs", EventType.PR_OPENED, "corr-docs"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=43,
        title="docs: update contributor guide",
        body="Clarifies wording only.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="docs/contributor-guide",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/43.diff",
        files_changed=(FileChange(path="docs/CONTRIBUTING.md", status="modified", additions=3, deletions=1),),
    )

    orchestrator = PRWorkflowOrchestrator()
    result = orchestrator.run(event)

    assert result.triage.depth is PRWorkflowDepth.LIGHTWEIGHT
    assert result.stage_order == (WorkflowStage.CONTEXT, WorkflowStage.TRIAGE, WorkflowStage.RENDERER)
    assert result.impact.areas == ()
    assert result.strategy.actions == ()
    assert result.validations == ()
    assert result.comment_payload is not None
    assert "Workflow depth: **LIGHTWEIGHT**" in result.comment_payload.body
    assert "Overall risk: **NOT ASSESSED**" in result.comment_payload.body
    assert "Triaged analysis/validation stages: `none`" in result.comment_payload.body
    assert "Allowed stages after triage" not in result.comment_payload.body
    assert "full analysis was skipped" in result.comment_payload.body
    assert "docs/CONTRIBUTING.md" in result.comment_payload.body

    assert result.impact.overall_risk is RiskLevel.NOT_ASSESSED


def test_rule_based_triage_does_not_default_github_config_or_empty_files_to_lightweight() -> None:
    workflow_event = PROpened(
        meta=_event_meta("evt-workflow", EventType.PR_OPENED, "corr-workflow"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=46,
        title="ci: update python matrix",
        body="Updates GitHub Actions CI configuration.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="ci/python-matrix",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/46.diff",
        files_changed=(FileChange(path=".github/workflows/ci.yml", status="modified", additions=2, deletions=1),),
    )
    empty_files_event = PROpened(
        meta=_event_meta("evt-empty-files", EventType.PR_OPENED, "corr-empty-files"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=47,
        title="chore: update metadata",
        body="File list is unavailable in this event context.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="chore/metadata",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/47.diff",
        files_changed=(),
    )

    workflow_result = PRWorkflowOrchestrator().run(workflow_event)
    empty_files_result = PRWorkflowOrchestrator().run(empty_files_event)

    assert workflow_result.triage.depth is PRWorkflowDepth.NORMAL
    assert WorkflowStage.ANALYZER in workflow_result.stage_order
    assert empty_files_result.triage.depth is PRWorkflowDepth.NORMAL
    assert WorkflowStage.ANALYZER in empty_files_result.stage_order


def test_pr_workflow_orchestrator_rejects_classifier_with_non_callable_classify_attribute() -> None:
    class InvalidClassifier:
        classify = "not callable"

    with pytest.raises(TypeError, match="triage_classifier"):
        PRWorkflowOrchestrator(triage_classifier=InvalidClassifier())  # type: ignore[arg-type]


def test_rule_based_triage_deep_signal_matching_uses_token_boundaries() -> None:
    classifier = RuleBasedPRWorkflowTriageClassifier()

    false_positive_event = PROpened(
        meta=_event_meta("evt-false-positive", EventType.PR_OPENED, "corr-false-positive"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=44,
        title="docs: author capitalization cleanup",
        body="Updates author names and capital letters only.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="docs/author-capitalization",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/44.diff",
        files_changed=(
            FileChange(
                path="docs/author-capitalization.md",
                status="modified",
                additions=2,
                deletions=1,
            ),
        ),
    )
    deep_signal_event = PROpened(
        meta=_event_meta("evt-auth-docs", EventType.PR_OPENED, "corr-auth-docs"),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=45,
        title="docs: update auth runbook",
        body="Documents the auth recovery runbook.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="docs/auth-runbook",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/45.diff",
        files_changed=(
            FileChange(
                path="docs/auth-runbook.md",
                status="modified",
                additions=2,
                deletions=1,
            ),
        ),
    )

    false_positive_result = PRWorkflowOrchestrator(triage_classifier=classifier).run(false_positive_event)
    deep_signal_result = PRWorkflowOrchestrator(triage_classifier=classifier).run(deep_signal_event)

    assert false_positive_result.triage.depth is PRWorkflowDepth.LIGHTWEIGHT
    assert deep_signal_result.triage.depth is PRWorkflowDepth.DEEP


def test_pr_workflow_orchestrator_uses_renders_output_contract_for_noop() -> None:
    triage = PRWorkflowTriage(
        depth=PRWorkflowDepth.NOOP,
        rationale="Generated metadata change does not need qaestro analysis.",
        allowed_stages=(WorkflowStage.RENDERER,),
    )
    orchestrator = PRWorkflowOrchestrator(triage_classifier=lambda context: triage)

    result = orchestrator.run(_pr_opened_event())

    assert triage.renders_output is False
    assert result.stage_order == (WorkflowStage.CONTEXT, WorkflowStage.TRIAGE)
    assert result.comment_payload is None


def test_pr_workflow_orchestrator_uses_deep_triage_to_force_validation() -> None:
    class RecordingValidator:
        def __init__(self) -> None:
            self.calls: list[StrategyResult] = []

        def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
            self.calls.append(strategy)
            return ()

    validator = RecordingValidator()
    triage = PRWorkflowTriage(
        depth=PRWorkflowDepth.DEEP,
        rationale="High-impact security runbook change requires deep validation.",
        allowed_stages=(WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR),
    )
    orchestrator = PRWorkflowOrchestrator(
        triage_classifier=lambda context: triage,
        should_validate=lambda event, impact, strategy: False,
        validator=validator,
    )

    result = orchestrator.run(_pr_opened_event())

    assert result.triage == triage
    assert validator.calls == [result.strategy]
    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.TRIAGE,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.VALIDATOR,
        WorkflowStage.RENDERER,
    )
    assert result.comment_payload is not None
    assert "Workflow depth: **DEEP**" in result.comment_payload.body


def test_pr_workflow_orchestrator_can_return_noop_triage_result() -> None:
    triage = PRWorkflowTriage(
        depth=PRWorkflowDepth.NOOP,
        rationale="Generated metadata change does not need qaestro analysis.",
        allowed_stages=(),
    )
    orchestrator = PRWorkflowOrchestrator(triage_classifier=lambda context: triage)

    result = orchestrator.run(_pr_opened_event())

    assert result.triage == triage
    assert result.stage_order == (WorkflowStage.CONTEXT, WorkflowStage.TRIAGE)
    assert result.comment_payload is None
    assert result.impact.summary == "Generated metadata change does not need qaestro analysis."


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
    assert result.stage_order == (
        WorkflowStage.CONTEXT,
        WorkflowStage.TRIAGE,
        WorkflowStage.ANALYZER,
        WorkflowStage.STRATEGY,
        WorkflowStage.VALIDATOR,
        WorkflowStage.RENDERER,
    )
