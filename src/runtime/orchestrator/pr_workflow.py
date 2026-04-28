"""PR-event workflow orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from src.adapters.renderers import GitHubPRCommentRenderer, PRCommentPayload
from src.core.analyzer import PRAnalysisContext, RuleBasedPRBehaviourAnalyzer
from src.core.contracts import (
    BehaviourImpact,
    PREvent,
    QAReport,
    RiskLevel,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)
from src.core.strategy import RuleBasedPRStrategyEngine
from src.runtime.stages import WorkflowStage

from .pr_context import EventPRContextProvider, PRContextProvider
from .pr_triage import PRWorkflowDepth, PRWorkflowTriage, RuleBasedPRWorkflowTriageClassifier
from .types import (
    PRBehaviourAnalyzer,
    PRRuntimeValidator,
    PRStrategyEngine,
    PRTriageClassifier,
    PRWorkflowDraft,
    PRWorkflowRenderer,
    PRWorkflowResult,
    ShouldValidate,
)


class PRWorkflowOrchestrator:
    """Coordinate PR context, triage, analysis, strategy, validation, and rendering."""

    def __init__(
        self,
        *,
        context_provider: PRContextProvider | None = None,
        triage_classifier: PRTriageClassifier | Callable[[PRAnalysisContext], PRWorkflowTriage] | None = None,
        analyzer: PRBehaviourAnalyzer | None = None,
        strategy_engine: PRStrategyEngine | None = None,
        validator: PRRuntimeValidator | None = None,
        renderer: PRWorkflowRenderer | None = None,
        should_validate: ShouldValidate | None = None,
    ) -> None:
        self._context_provider = context_provider or EventPRContextProvider()
        self._triage_classifier = _as_triage_classifier(triage_classifier or RuleBasedPRWorkflowTriageClassifier())
        self._analyzer = analyzer or RuleBasedPRBehaviourAnalyzer()
        self._strategy_engine = strategy_engine or RuleBasedPRStrategyEngine()
        self._validator = validator or StubPRRuntimeValidator()
        self._renderer = renderer or _DefaultDraftRenderer()
        self._should_validate = should_validate or (lambda event, impact, strategy: True)

    def run(self, event: PREvent) -> PRWorkflowResult:
        """Run the bounded PR workflow for one normalized event."""
        stages: list[WorkflowStage] = []

        stages.append(WorkflowStage.CONTEXT)
        context = self._context_provider.load(event)

        stages.append(WorkflowStage.TRIAGE)
        triage = self._triage_classifier.classify(context)

        if not triage.renders_output:
            report = _triage_only_report(event, context, triage)
            return PRWorkflowResult(
                event=event,
                report=report,
                triage=triage,
                comment_payload=None,
                stage_order=tuple(stages),
            )

        if not triage.runs_analysis:
            report = _triage_only_report(event, context, triage)
            stage_order = (*stages, WorkflowStage.RENDERER)
            draft = PRWorkflowDraft(event=event, report=report, triage=triage, stage_order=stage_order)
            comment_payload = self._renderer.render(draft)
            return PRWorkflowResult(
                event=event,
                report=report,
                triage=triage,
                comment_payload=comment_payload,
                stage_order=stage_order,
            )

        stages.append(WorkflowStage.ANALYZER)
        impact = self._analyzer.analyze(context)

        strategy: StrategyResult
        if triage.runs_strategy:
            stages.append(WorkflowStage.STRATEGY)
            strategy = self._strategy_engine.plan(
                repo_full_name=context.repo_full_name,
                pr_number=context.pr_number,
                title=context.title,
                impact=impact,
            )
        else:
            strategy = _empty_strategy(triage)

        validations: tuple[ValidationResult, ...]
        if triage.allows_validation and (
            triage.depth is PRWorkflowDepth.DEEP or self._should_validate(event, impact, strategy)
        ):
            stages.append(WorkflowStage.VALIDATOR)
            validations = self._validator.validate(strategy)
        else:
            validations = ()

        report = QAReport(
            event_id=event.meta.event_id,
            repo_full_name=context.repo_full_name,
            pr_number=context.pr_number,
            impact=impact,
            strategy=strategy,
            validations=validations,
            summary_markdown=impact.summary,
        )
        stage_order = (*stages, WorkflowStage.RENDERER)
        draft = PRWorkflowDraft(event=event, report=report, triage=triage, stage_order=stage_order)
        comment_payload = self._renderer.render(draft)
        return PRWorkflowResult(
            event=event,
            report=report,
            triage=triage,
            comment_payload=comment_payload,
            stage_order=stage_order,
        )


class _DefaultDraftRenderer:
    """Bridge the PR workflow draft contract to the GitHub comment renderer."""

    def __init__(self) -> None:
        self._renderer = GitHubPRCommentRenderer()

    def render(self, draft: PRWorkflowDraft) -> PRCommentPayload:
        return self._renderer.render(draft.report, correlation_id=draft.correlation_id, triage=draft.triage)


class StubPRRuntimeValidator:
    """Return skipped validation placeholders until runtime validation exists.

    No probes, tests, or external checks run here. Later milestones should route
    selected strategy actions to runtime validators and replace SKIPPED with real
    validation outcomes.
    """

    def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
        return tuple(
            ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details="Runtime validation is not executed in Step 3.",
            )
            for action in strategy.actions
        )


class _CallableTriageClassifier:
    """Adapter that lets tests and future runners inject a simple callable."""

    def __init__(self, classify: Callable[[PRAnalysisContext], PRWorkflowTriage]) -> None:
        self._classify = classify

    def classify(self, context: PRAnalysisContext) -> PRWorkflowTriage:
        return self._classify(context)


def _as_triage_classifier(
    classifier: PRTriageClassifier | Callable[[PRAnalysisContext], PRWorkflowTriage],
) -> PRTriageClassifier:
    classify = getattr(classifier, "classify", None)
    if callable(classify):
        return cast(PRTriageClassifier, classifier)
    if callable(classifier):
        return _CallableTriageClassifier(classifier)
    raise TypeError("triage_classifier must be callable or expose a callable classify(context) method")


def _triage_only_report(event: PREvent, context: PRAnalysisContext, triage: PRWorkflowTriage) -> QAReport:
    """Build an auditable no-op/lightweight report without full analysis output."""
    impact = BehaviourImpact(
        summary=triage.rationale,
        areas=(),
        # Stub-only neutral risk: lightweight/no-op triage intentionally avoids
        # full behaviour risk evaluation, so this must not be read as a real
        # risk decision for the PR.
        overall_risk=RiskLevel.LOW,
        raw_diff_stats={
            "files_changed": len(context.files),
            "additions": sum(file.additions for file in context.files),
            "deletions": sum(file.deletions for file in context.files),
        },
    )
    return QAReport(
        event_id=event.meta.event_id,
        repo_full_name=context.repo_full_name,
        pr_number=context.pr_number,
        impact=impact,
        strategy=_empty_strategy(triage),
        validations=(),
        summary_markdown=_triage_summary(context, triage),
    )


def _empty_strategy(triage: PRWorkflowTriage) -> StrategyResult:
    """Return explicit empty strategy output for skipped strategy paths."""
    return StrategyResult(actions=(), reasoning=triage.rationale, confidence=0.0)


def _triage_summary(context: PRAnalysisContext, triage: PRWorkflowTriage) -> str:
    changed_paths = ", ".join(f"`{file.path}`" for file in context.files[:5]) or "no files"
    return (
        f"Workflow depth `{triage.depth.value}` selected after context triage; "
        f"{triage.rationale} Changed files: {changed_paths}."
    )
