"""Top-level event dispatch orchestration."""

from __future__ import annotations

from src.core.contracts import (
    BehaviourImpact,
    ChatMention,
    CICompleted,
    Event,
    PRCommented,
    PREvent,
    PRReviewed,
    PRReviewRequested,
    PRReviewRequestRemoved,
    PRUpdated,
    QAReport,
    RiskLevel,
    StrategyResult,
)

from .chat_workflow import ChatWorkflowOrchestrator
from .ci_workflow import CIWorkflowOrchestrator, CIWorkflowResult
from .pr_aggregate import InMemoryPRAggregateStore, PRAggregateState
from .pr_event_stubs import PRCommentWorkflowOrchestrator, PRReviewWorkflowOrchestrator
from .pr_triage import PRWorkflowDepth, PRWorkflowTriage
from .pr_workflow import PRWorkflowOrchestrator
from .types import PRWorkflowResult, UnsupportedEventError


class EventOrchestrator:
    """Route normalized events to event-type-specific workflow orchestrators."""

    def __init__(
        self,
        *,
        pr_orchestrator: PRWorkflowOrchestrator | None = None,
        pr_comment_orchestrator: PRCommentWorkflowOrchestrator | None = None,
        pr_review_orchestrator: PRReviewWorkflowOrchestrator | None = None,
        ci_orchestrator: CIWorkflowOrchestrator | None = None,
        chat_orchestrator: ChatWorkflowOrchestrator | None = None,
        aggregate_store: InMemoryPRAggregateStore | None = None,
        activation_reviewer_logins: tuple[str, ...] = (),
        activation_team_slugs: tuple[str, ...] = (),
    ) -> None:
        self._pr_orchestrator = pr_orchestrator or PRWorkflowOrchestrator()
        self._pr_comment_orchestrator = pr_comment_orchestrator or PRCommentWorkflowOrchestrator()
        self._pr_review_orchestrator = pr_review_orchestrator or PRReviewWorkflowOrchestrator()
        self._ci_orchestrator = ci_orchestrator or CIWorkflowOrchestrator()
        self._chat_orchestrator = chat_orchestrator or ChatWorkflowOrchestrator()
        self._aggregate_store = aggregate_store or InMemoryPRAggregateStore()
        self._activation_reviewer_logins = activation_reviewer_logins
        self._activation_team_slugs = activation_team_slugs

    def run(self, event: Event) -> PRWorkflowResult | CIWorkflowResult:
        if isinstance(event, (PRReviewRequested, PRReviewRequestRemoved)):
            if not self._activation_enabled or not event.matches_identity(
                reviewer_logins=self._activation_reviewer_logins,
                team_slugs=self._activation_team_slugs,
            ):
                return _noop_pr_result(event)
            if self._activation_enabled:
                aggregate = self._aggregate_store.apply_pr_event(
                    event,
                    qaestro_reviewers=self._activation_reviewer_logins,
                    qaestro_teams=self._activation_team_slugs,
                )
                if isinstance(event, PRReviewRequestRemoved) or not aggregate.qaestro_active:
                    return _noop_pr_result(event)
            return self._pr_orchestrator.run(event)
        if isinstance(event, PREvent):
            if self._activation_enabled:
                aggregate = self._aggregate_store.apply_pr_event(
                    event,
                    qaestro_reviewers=self._activation_reviewer_logins,
                    qaestro_teams=self._activation_team_slugs,
                )
                if isinstance(event, PRReviewRequestRemoved) or not aggregate.qaestro_active:
                    return _noop_pr_result(event)
            return self._pr_orchestrator.run(event)
        if isinstance(event, PRCommented):
            return self._pr_comment_orchestrator.run(event)
        if isinstance(event, PRReviewed):
            return self._pr_review_orchestrator.run(event)
        if isinstance(event, CICompleted):
            result = self._ci_orchestrator.run(event)
            if self._activation_enabled:
                ci_aggregate = self._aggregate_for_ci(result.event)
                if ci_aggregate is not None:
                    return self._pr_orchestrator.run(_pr_event_from_ci(result.event, ci_aggregate))
            return result
        if isinstance(event, ChatMention):
            return self._chat_orchestrator.run(event)
        raise UnsupportedEventError(f"No workflow orchestrator registered for {type(event).__name__}")

    @property
    def _activation_enabled(self) -> bool:
        return bool(self._activation_reviewer_logins or self._activation_team_slugs)

    def _aggregate_for_ci(self, event: CICompleted) -> PRAggregateState | None:
        if event.pr_number is None:
            return None
        aggregate = self._aggregate_store.get(event.repo_full_name, event.pr_number)
        if aggregate is None or not aggregate.qaestro_active:
            return None
        if event.commit_sha != aggregate.current_head_sha:
            return None
        return aggregate


def _noop_pr_result(event: PREvent) -> PRWorkflowResult:
    impact = BehaviourImpact(
        summary="Qaestro reviewer-request activation did not match; full QA workflow was not started.",
        areas=(),
        overall_risk=RiskLevel.NOT_ASSESSED,
    )
    report = QAReport(
        event_id=event.meta.event_id,
        repo_full_name=event.repo_full_name,
        pr_number=event.pr_number,
        impact=impact,
        strategy=StrategyResult(
            actions=(), reasoning="Reviewer-request activation gate skipped this event.", confidence=1.0
        ),
        validations=(),
        summary_markdown=impact.summary,
    )
    return PRWorkflowResult(
        event=event,
        report=report,
        triage=_noop_triage(),
        comment_payload=None,
        stage_order=(),
    )


def _noop_triage() -> PRWorkflowTriage:
    return PRWorkflowTriage(
        depth=PRWorkflowDepth.NOOP,
        rationale="Reviewer-request activation gate skipped this event.",
        allowed_stages=(),
    )


def _pr_event_from_ci(event: CICompleted, aggregate: PRAggregateState) -> PREvent:
    return PRUpdated(
        meta=event.meta,
        repo_full_name=aggregate.repo_full_name,
        pr_number=aggregate.pr_number,
        title=aggregate.title,
        body="",
        author="",
        base_branch="",
        head_branch="",
        diff_url="",
        head_sha=aggregate.current_head_sha,
    )
