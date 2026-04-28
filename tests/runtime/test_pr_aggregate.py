"""Tests for PR aggregate state and current-head review readiness."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.contracts import CICompleted, EventMeta, EventSource, EventType, FileChange, PROpened, PRUpdated
from src.runtime.orchestrator import (
    CheckRunSnapshot,
    CheckRunStatus,
    PRAggregateState,
    PRRevisionStatus,
    ReviewReadinessState,
    ReviewRunTrigger,
)


def _meta(event_id: str, event_type: EventType) -> EventMeta:
    return EventMeta(
        event_id=event_id,
        event_type=event_type,
        correlation_id=f"corr-{event_id}",
        timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


def _pr_event(*, event_id: str = "pr-open", head_sha: str = "sha-1") -> PROpened:
    return PROpened(
        meta=_meta(event_id, EventType.PR_OPENED),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=54,
        title="feat: aggregate readiness",
        body="Wire PR aggregate state.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/pr-aggregate",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/54.diff",
        head_sha=head_sha,
        files_changed=(FileChange(path="src/runtime/orchestrator/pr_aggregate.py", status="added", additions=80),),
    )


def _pr_update(*, event_id: str = "pr-update", head_sha: str = "sha-2") -> PRUpdated:
    return PRUpdated(
        meta=_meta(event_id, EventType.PR_UPDATED),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=54,
        title="feat: aggregate readiness",
        body="Wire PR aggregate state.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/pr-aggregate",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/54.diff",
        head_sha=head_sha,
        files_changed=(FileChange(path="src/runtime/orchestrator/pr_aggregate.py", status="modified", additions=20),),
    )


def _ci_event(*, event_id: str, commit_sha: str, conclusion: str, workflow_name: str = "Tests") -> CICompleted:
    return CICompleted(
        meta=_meta(event_id, EventType.CI_COMPLETED),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=54,
        commit_sha=commit_sha,
        workflow_name=workflow_name,
        conclusion=conclusion,
        run_url=f"https://github.com/Kimcheolhui/qaestro/actions/runs/{event_id}",
        failed_jobs=("pytest",) if conclusion == "failure" else (),
        run_id=123,
    )


def test_pr_event_starts_aggregate_with_current_revision() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-1"))

    assert aggregate.repo_full_name == "Kimcheolhui/qaestro"
    assert aggregate.pr_number == 54
    assert aggregate.current_head_sha == "sha-1"
    assert aggregate.current_revision.head_sha == "sha-1"
    assert aggregate.current_revision.status is PRRevisionStatus.CURRENT
    assert aggregate.event_ids == ("pr-open",)


def test_new_pr_head_supersedes_previous_revision_but_keeps_historical_evidence() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-1"))
    aggregate = aggregate.record_ci_completed(_ci_event(event_id="ci-old", commit_sha="sha-1", conclusion="failure"))

    aggregate = aggregate.apply_pr_event(_pr_update(head_sha="sha-2"))

    assert aggregate.current_head_sha == "sha-2"
    assert aggregate.revisions["sha-1"].status is PRRevisionStatus.SUPERSEDED
    assert aggregate.revisions["sha-1"].ci_runs[0].conclusion == "failure"
    assert aggregate.current_revision.head_sha == "sha-2"
    assert aggregate.current_revision.ci_runs == ()
    assert aggregate.current_revision.status is PRRevisionStatus.CURRENT


def test_stale_ci_result_is_recorded_without_affecting_current_readiness() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-1"))
    aggregate = aggregate.apply_pr_event(_pr_update(head_sha="sha-2"))

    aggregate = aggregate.record_ci_completed(_ci_event(event_id="ci-stale", commit_sha="sha-1", conclusion="failure"))
    readiness = aggregate.evaluate_readiness(
        current_check_snapshot=(
            CheckRunSnapshot(name="Tests", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha="sha-2"),
        )
    )

    assert aggregate.revisions["sha-1"].ci_runs[0].is_current_head is False
    assert readiness.state is ReviewReadinessState.READY
    assert readiness.head_sha == "sha-2"
    assert readiness.blocking_checks == ()


def test_failed_current_head_check_is_ready_for_final_review_with_failure_state() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-2"))

    readiness = aggregate.evaluate_readiness(
        current_check_snapshot=(
            CheckRunSnapshot(name="Tests", status=CheckRunStatus.COMPLETED, conclusion="failure", head_sha="sha-2"),
        )
    )

    assert readiness.state is ReviewReadinessState.CHECKS_FAILED
    assert readiness.can_publish_final_review is True
    assert readiness.blocking_checks == ("Tests",)


def test_requested_or_unknown_check_status_is_treated_as_pending_not_crashing() -> None:
    requested = CheckRunSnapshot(name="Security", status="requested", conclusion=None, head_sha="sha-2")
    unknown = CheckRunSnapshot(name="External", status="custom_pending", conclusion=None, head_sha="sha-2")

    assert requested.status is CheckRunStatus.PENDING
    assert requested.is_pending is True
    assert unknown.status is CheckRunStatus.UNKNOWN
    assert unknown.is_pending is True


def test_pending_current_head_check_blocks_final_review_readiness() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-2"))

    readiness = aggregate.evaluate_readiness(
        current_check_snapshot=(
            CheckRunSnapshot(name="Lint", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha="sha-2"),
            CheckRunSnapshot(name="Tests", status=CheckRunStatus.IN_PROGRESS, conclusion=None, head_sha="sha-2"),
        )
    )

    assert readiness.state is ReviewReadinessState.WAITING_FOR_CHECKS
    assert readiness.can_publish_final_review is False
    assert readiness.blocking_checks == ("Tests",)
    assert "Tests" in readiness.summary


def test_manual_trigger_records_review_run_and_allows_interim_response() -> None:
    aggregate = PRAggregateState.from_pr_event(_pr_event(head_sha="sha-2"))
    aggregate = aggregate.start_review_run(trigger=ReviewRunTrigger.MANUAL, requested_by="Kimcheolhui")

    readiness = aggregate.evaluate_readiness(
        current_check_snapshot=(
            CheckRunSnapshot(name="Tests", status=CheckRunStatus.QUEUED, conclusion=None, head_sha="sha-2"),
        )
    )

    assert aggregate.review_runs[-1].trigger is ReviewRunTrigger.MANUAL
    assert aggregate.review_runs[-1].head_sha == "sha-2"
    assert readiness.state is ReviewReadinessState.WAITING_FOR_CHECKS
    assert readiness.can_publish_interim_response is True
    assert readiness.can_publish_final_review is False
