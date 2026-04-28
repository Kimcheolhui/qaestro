"""PR aggregate state and current-head review readiness contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from src.adapters.connectors.github import CheckRunResult
from src.core.contracts import CICompleted, PREvent


class PRRevisionStatus(StrEnum):
    """Lifecycle status for a PR head revision tracked inside an aggregate."""

    CURRENT = "current"
    SUPERSEDED = "superseded"


class CheckRunStatus(StrEnum):
    """Normalized check/workflow execution status for current-head readiness."""

    UNKNOWN = "unknown"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    COMPLETED = "completed"


class ReviewReadinessState(StrEnum):
    """Whether qaestro can publish a final unified review for the current head."""

    READY = "ready"
    WAITING_FOR_CHECKS = "waiting_for_checks"
    CHECKS_FAILED = "checks_failed"


class ReviewRunTrigger(StrEnum):
    """Origin of a review run request tracked in PR aggregate history."""

    MANUAL = "manual"
    AUTO = "auto"
    CI_COMPLETED = "ci_completed"


@dataclass(frozen=True)
class CheckRunSnapshot:
    """Current-head check/workflow snapshot used to gate final review publication."""

    name: str
    status: CheckRunStatus | str
    conclusion: str | None
    head_sha: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _normalize_check_run_status(self.status))

    @property
    def is_pending(self) -> bool:
        return self.status is not CheckRunStatus.COMPLETED

    @property
    def is_failure(self) -> bool:
        return self.status is CheckRunStatus.COMPLETED and (self.conclusion or "").lower() in {
            "action_required",
            "failure",
            "startup_failure",
            "timed_out",
        }

    @classmethod
    def from_result(cls, result: CheckRunResult) -> CheckRunSnapshot:
        return cls(
            name=result.name,
            status=result.status,
            conclusion=result.conclusion or None,
            head_sha=result.head_sha,
        )


@dataclass(frozen=True)
class CIWorkflowRunRecord:
    """CI workflow completion recorded against the commit sha it reported."""

    event_id: str
    workflow_name: str
    conclusion: str
    run_url: str
    failed_jobs: tuple[str, ...]
    commit_sha: str
    is_current_head: bool

    @classmethod
    def from_event(cls, event: CICompleted, *, current_head_sha: str) -> CIWorkflowRunRecord:
        return cls(
            event_id=event.meta.event_id,
            workflow_name=event.workflow_name,
            conclusion=event.conclusion,
            run_url=event.run_url,
            failed_jobs=event.failed_jobs,
            commit_sha=event.commit_sha,
            is_current_head=event.commit_sha == current_head_sha,
        )


@dataclass(frozen=True)
class PRRevisionState:
    """State for one PR head commit.

    Analysis and CI data from superseded revisions remains historical evidence.
    Current verdict/readiness logic must use only the revision whose ``head_sha``
    matches ``PRAggregateState.current_head_sha``.
    """

    head_sha: str
    status: PRRevisionStatus
    ci_runs: tuple[CIWorkflowRunRecord, ...] = ()

    def record_ci_run(self, record: CIWorkflowRunRecord) -> PRRevisionState:
        return replace(self, ci_runs=(*self.ci_runs, record))

    def supersede(self) -> PRRevisionState:
        if self.status is PRRevisionStatus.SUPERSEDED:
            return self
        return replace(self, status=PRRevisionStatus.SUPERSEDED)


@dataclass(frozen=True)
class ReviewRun:
    """One requested/started review run for a PR revision."""

    head_sha: str
    trigger: ReviewRunTrigger
    requested_by: str = ""


@dataclass(frozen=True)
class ReviewReadiness:
    """Readiness verdict for final or interim review output."""

    state: ReviewReadinessState
    head_sha: str
    blocking_checks: tuple[str, ...] = ()
    summary: str = ""

    @property
    def can_publish_final_review(self) -> bool:
        return self.state in {ReviewReadinessState.READY, ReviewReadinessState.CHECKS_FAILED}

    @property
    def can_publish_interim_response(self) -> bool:
        return self.state is ReviewReadinessState.WAITING_FOR_CHECKS


@dataclass(frozen=True)
class PRAggregateState:
    """PR-level state shared by PR, CI, and manual review-trigger events."""

    repo_full_name: str
    pr_number: int
    title: str
    current_head_sha: str
    revisions: dict[str, PRRevisionState] = field(default_factory=dict)
    event_ids: tuple[str, ...] = ()
    review_runs: tuple[ReviewRun, ...] = ()

    @classmethod
    def from_pr_event(cls, event: PREvent) -> PRAggregateState:
        head_sha = _head_sha_for(event)
        return cls(
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            title=event.title,
            current_head_sha=head_sha,
            revisions={head_sha: PRRevisionState(head_sha=head_sha, status=PRRevisionStatus.CURRENT)},
            event_ids=(event.meta.event_id,),
        )

    @property
    def current_revision(self) -> PRRevisionState:
        return self.revisions[self.current_head_sha]

    def apply_pr_event(self, event: PREvent) -> PRAggregateState:
        head_sha = _head_sha_for(event)
        revisions = dict(self.revisions)
        if head_sha != self.current_head_sha:
            revisions = {
                sha: revision.supersede() if sha == self.current_head_sha else revision
                for sha, revision in revisions.items()
            }
        revisions[head_sha] = replace(
            revisions.get(head_sha, PRRevisionState(head_sha=head_sha, status=PRRevisionStatus.CURRENT)),
            status=PRRevisionStatus.CURRENT,
        )
        return replace(
            self,
            title=event.title or self.title,
            current_head_sha=head_sha,
            revisions=revisions,
            event_ids=_append_unique(self.event_ids, event.meta.event_id),
        )

    def record_ci_completed(self, event: CICompleted) -> PRAggregateState:
        record = CIWorkflowRunRecord.from_event(event, current_head_sha=self.current_head_sha)
        revisions = dict(self.revisions)
        if event.commit_sha not in revisions:
            revisions[event.commit_sha] = PRRevisionState(
                head_sha=event.commit_sha,
                status=PRRevisionStatus.SUPERSEDED,
            )
        revisions[event.commit_sha] = revisions[event.commit_sha].record_ci_run(record)
        return replace(self, revisions=revisions, event_ids=_append_unique(self.event_ids, event.meta.event_id))

    def start_review_run(self, *, trigger: ReviewRunTrigger, requested_by: str = "") -> PRAggregateState:
        run = ReviewRun(head_sha=self.current_head_sha, trigger=trigger, requested_by=requested_by)
        return replace(self, review_runs=(*self.review_runs, run))

    def evaluate_readiness(self, *, current_check_snapshot: tuple[CheckRunSnapshot, ...]) -> ReviewReadiness:
        current_checks = tuple(check for check in current_check_snapshot if check.head_sha == self.current_head_sha)
        blocking = tuple(check.name for check in current_checks if check.is_pending)
        if blocking:
            check_list = ", ".join(blocking)
            return ReviewReadiness(
                state=ReviewReadinessState.WAITING_FOR_CHECKS,
                head_sha=self.current_head_sha,
                blocking_checks=blocking,
                summary=f"Waiting for current-head checks to finish: {check_list}.",
            )
        failed = tuple(check.name for check in current_checks if check.is_failure)
        if failed:
            check_list = ", ".join(failed)
            return ReviewReadiness(
                state=ReviewReadinessState.CHECKS_FAILED,
                head_sha=self.current_head_sha,
                blocking_checks=failed,
                summary=f"Current-head checks completed with failures: {check_list}.",
            )
        return ReviewReadiness(
            state=ReviewReadinessState.READY,
            head_sha=self.current_head_sha,
            summary="Current-head checks are complete; final review can be published.",
        )


class InMemoryPRAggregateStore:
    """Minimal in-memory store for deterministic tests and future worker wiring."""

    def __init__(self) -> None:
        self._aggregates: dict[tuple[str, int], PRAggregateState] = {}

    def get(self, repo_full_name: str, pr_number: int) -> PRAggregateState | None:
        return self._aggregates.get((repo_full_name, pr_number))

    def save(self, aggregate: PRAggregateState) -> PRAggregateState:
        self._aggregates[(aggregate.repo_full_name, aggregate.pr_number)] = aggregate
        return aggregate

    def apply_pr_event(self, event: PREvent) -> PRAggregateState:
        existing = self.get(event.repo_full_name, event.pr_number)
        aggregate = PRAggregateState.from_pr_event(event) if existing is None else existing.apply_pr_event(event)
        return self.save(aggregate)

    def record_ci_completed(self, event: CICompleted) -> PRAggregateState | None:
        if event.pr_number is None:
            return None
        existing = self.get(event.repo_full_name, event.pr_number)
        if existing is None:
            return None
        return self.save(existing.record_ci_completed(event))


def _head_sha_for(event: PREvent) -> str:
    head_sha = event.head_sha.strip()
    if not head_sha:
        raise ValueError("PR event head_sha is required for aggregate revision state")
    return head_sha


def _normalize_check_run_status(status: CheckRunStatus | str) -> CheckRunStatus:
    if isinstance(status, CheckRunStatus):
        return status
    normalized = status.strip().lower()
    aliases = {
        "requested": CheckRunStatus.PENDING,
        "waiting": CheckRunStatus.PENDING,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return CheckRunStatus(normalized)
    except ValueError:
        return CheckRunStatus.UNKNOWN


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return values
    return (*values, value)
