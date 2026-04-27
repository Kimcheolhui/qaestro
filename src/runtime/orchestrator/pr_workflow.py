"""PR-event workflow orchestration."""

from __future__ import annotations

from src.adapters.renderers import GitHubPRCommentRenderer, PRCommentPayload
from src.core.analyzer import PRAnalysisContext, RuleBasedPRBehaviourAnalyzer
from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    PREvent,
    QAReport,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)
from src.core.strategy import RuleBasedPRStrategyEngine

from .pr_context import EventPRContextProvider, PRContextProvider
from .types import (
    PRBehaviourAnalyzer,
    PRRuntimeValidator,
    PRStrategyEngine,
    PRWorkflowDraft,
    PRWorkflowRenderer,
    PRWorkflowResult,
    ShouldValidate,
)


class PRWorkflowOrchestrator:
    """Coordinate the PR-event workflow."""

    def __init__(
        self,
        *,
        context_provider: PRContextProvider | None = None,
        analyzer: PRBehaviourAnalyzer | None = None,
        strategy_engine: PRStrategyEngine | None = None,
        validator: PRRuntimeValidator | None = None,
        renderer: PRWorkflowRenderer | None = None,
        should_validate: ShouldValidate | None = None,
    ) -> None:
        self._context_provider = context_provider or EventPRContextProvider()
        self._analyzer = analyzer or RuleBasedPRBehaviourAnalyzer()
        self._strategy_engine = strategy_engine or RuleBasedPRStrategyEngine()
        self._validator = validator or StubPRRuntimeValidator()
        self._renderer = renderer or _DefaultDraftRenderer()
        self._should_validate = should_validate or (lambda event, impact, strategy: True)

    def run(self, event: PREvent) -> PRWorkflowResult:
        stages: list[str] = []

        stages.append("context")
        context = self._context_provider.load(event)

        stages.append("analyzer")
        impact = self._analyzer.analyze(context)

        stages.append("strategy")
        strategy = self._strategy_engine.plan(
            repo_full_name=context.repo_full_name,
            pr_number=context.pr_number,
            title=context.title,
            impact=impact,
        )

        validations: tuple[ValidationResult, ...]
        if self._should_validate(event, impact, strategy):
            stages.append("validator")
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

        stage_order = (*stages, "renderer")
        draft = PRWorkflowDraft(
            event=event,
            report=report,
            stage_order=stage_order,
        )
        comment_payload = self._renderer.render(draft)
        return PRWorkflowResult(
            event=event,
            report=report,
            comment_payload=comment_payload,
            stage_order=stage_order,
        )


class _DefaultDraftRenderer:
    def __init__(self) -> None:
        self._renderer = GitHubPRCommentRenderer()

    def render(self, draft: PRWorkflowDraft) -> PRCommentPayload:
        return self._renderer.render(draft.report, correlation_id=draft.correlation_id)


class StubPRBehaviourAnalyzer:
    """Legacy placeholder analyzer kept for tests that inject stubs explicitly.

    This is no longer the default Step 3 analyzer. It remains importable so older
    extension tests can still exercise orchestrator replaceability.
    """

    def analyze(self, context: PRAnalysisContext) -> BehaviourImpact:
        return RuleBasedPRBehaviourAnalyzer().analyze(context)


class StubPRStrategyEngine:
    """Legacy placeholder strategy engine kept for explicit compatibility tests."""

    def plan(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        title: str,
        impact: BehaviourImpact,
    ) -> StrategyResult:
        del repo_full_name, pr_number, title
        action = StrategyAction(
            action_type=ActionType.CUSTOM,
            description="Review Step 3 behaviour impact output",
            target="behaviour-impact-report",
            priority=0,
            rationale="Compatibility stub; production default uses RuleBasedPRStrategyEngine.",
        )
        return StrategyResult(
            actions=(action,),
            reasoning="Compatibility stub strategy; production default uses RuleBasedPRStrategyEngine.",
            confidence=0.0,
        )


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
