"""PR-event workflow orchestration."""

from __future__ import annotations

from src.adapters.renderers import GitHubPRCommentRenderer, PRCommentPayload
from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    ImpactArea,
    PREvent,
    QAReport,
    RiskLevel,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)

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
    """Coordinate the PR-event workflow.

    The default analyzer, strategy engine, and validator are stub components
    until later milestones replace them with real implementations. They are
    injected through protocols so each stage can be replaced independently
    without changing the orchestration sequence.
    """

    def __init__(
        self,
        *,
        analyzer: PRBehaviourAnalyzer | None = None,
        strategy_engine: PRStrategyEngine | None = None,
        validator: PRRuntimeValidator | None = None,
        renderer: PRWorkflowRenderer | None = None,
        should_validate: ShouldValidate | None = None,
    ) -> None:
        self._analyzer = analyzer or StubPRBehaviourAnalyzer()
        self._strategy_engine = strategy_engine or StubPRStrategyEngine()
        self._validator = validator or StubPRRuntimeValidator()
        self._renderer = renderer or _DefaultDraftRenderer()
        self._should_validate = should_validate or (lambda event, impact, strategy: True)

    def run(self, event: PREvent) -> PRWorkflowResult:
        stages: list[str] = []

        stages.append("analyzer")
        impact = self._analyzer.analyze(event)

        stages.append("strategy")
        strategy = self._strategy_engine.plan(event, impact)

        validations: tuple[ValidationResult, ...]
        if self._should_validate(event, impact, strategy):
            stages.append("validator")
            validations = self._validator.validate(strategy)
        else:
            validations = ()

        report = QAReport(
            event_id=event.meta.event_id,
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
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
    """Placeholder PR analyzer until real risk evaluation lands.

    The LOW risk values below are not risk decisions. They are deliberately
    neutral placeholders so Step 2 can exercise the orchestration contract.
    Replace this component with core analyzer/risk-evaluation logic in the
    Behaviour Impact Report milestone.
    """

    def analyze(self, event: PREvent) -> BehaviourImpact:
        areas = tuple(
            ImpactArea(
                module=_module_for_file(change.path),
                description=f"{change.status} {change.path}",
                # Stub only: do not treat this as a real per-file risk score.
                # Later analyzer logic must evaluate risk from diff semantics,
                # affected modules, test coverage, runtime ownership, and history.
                risk_level=RiskLevel.LOW,
                affected_files=(change.path,),
            )
            for change in event.files_changed
        )
        return BehaviourImpact(
            summary=f"Step 2 stub analysis for PR #{event.pr_number}: {event.title}",
            areas=areas,
            # Stub only: overall risk is fixed to LOW until actual risk aggregation
            # is implemented from the analyzer output.
            overall_risk=RiskLevel.LOW,
            raw_diff_stats={
                "files_changed": len(event.files_changed),
                "additions": sum(change.additions for change in event.files_changed),
                "deletions": sum(change.deletions for change in event.files_changed),
            },
        )


class StubPRStrategyEngine:
    """Placeholder PR strategy engine until real strategy selection is wired.

    The CUSTOM action and zero confidence below only document that the pipeline
    reached the strategy stage. They must be replaced by real behaviour-checklist
    and validation-plan selection logic.
    """

    def plan(self, event: PREvent, impact: BehaviourImpact) -> StrategyResult:
        action = StrategyAction(
            # Stub only: this is not the final action taxonomy selection.
            action_type=ActionType.CUSTOM,
            description="Review Step 2 stub output",
            target=f"{event.repo_full_name}#{event.pr_number}",
            priority=0,
            rationale="Step 2 wires the workflow only; real strategy is introduced in Step 3.",
        )
        return StrategyResult(
            actions=(action,),
            reasoning="Step 2 stub strategy; real strategy is introduced in Step 3.",
            # Stub only: confidence is unknown until strategy scoring exists.
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
                # Stub only: every action is marked SKIPPED because Step 2 does not
                # execute runtime validation yet.
                outcome=ValidationOutcome.SKIPPED,
                details="Step 2 does not execute runtime validation yet.",
            )
            for action in strategy.actions
        )


def _module_for_file(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "src":
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return path or "unknown"
