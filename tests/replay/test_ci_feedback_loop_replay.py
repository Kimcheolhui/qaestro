"""Replay/integration coverage for Step 4 CI feedback loop scenarios."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from src.adapters.renderers import PRCommentPayload, PRReviewPayload
from src.app.gateway import GitHubWebhookGateway, WebhookRequest
from src.app.jobs import InMemoryJobQueue
from src.app.worker import Worker, WorkerStatus
from src.core.contracts import CICompleted, CIFeedbackContext, CIReadinessState, PREvent
from src.core.contracts.parsers import parse_github_ci_event
from src.runtime.orchestrator import (
    CheckRunSnapshot,
    CheckRunStatus,
    CIWorkflowDepth,
    CIWorkflowOrchestrator,
    EventOrchestrator,
    InMemoryPRAggregateStore,
    PRCheckSnapshotProvider,
    PRWorkflowOrchestrator,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SECRET = "***"
OLD_HEAD_SHA = "def789abc123456"
CURRENT_HEAD_SHA = "fed321cba987654"


class RecordingOutputPoster:
    def __init__(self) -> None:
        self.payloads: list[PRCommentPayload] = []
        self.review_payloads: list[PRReviewPayload | None] = []
        self.correlation_ids: list[str] = []

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> object:
        self.payloads.append(payload)
        self.review_payloads.append(None)
        self.correlation_ids.append(correlation_id)
        return correlation_id

    def post_outputs(
        self, payload: PRCommentPayload, *, review_payload: PRReviewPayload | None, correlation_id: str
    ) -> object:
        self.payloads.append(payload)
        self.review_payloads.append(review_payload)
        self.correlation_ids.append(correlation_id)
        return correlation_id


class MutableCheckSnapshotProvider(PRCheckSnapshotProvider):
    def __init__(self) -> None:
        self.snapshots_by_head: dict[str, tuple[CheckRunSnapshot, ...]] = {}
        self.calls: list[tuple[str, str, str]] = []

    def load(self, *, repo_full_name: str, head_sha: str, correlation_id: str) -> tuple[CheckRunSnapshot, ...]:
        self.calls.append((repo_full_name, head_sha, correlation_id))
        return self.snapshots_by_head.get(head_sha, ())


def _signature(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _request(fixture_name: str, *, event_name: str, delivery: str) -> WebhookRequest:
    return _request_from_body((FIXTURES / fixture_name).read_bytes(), event_name=event_name, delivery=delivery)


def _request_from_body(body: bytes, *, event_name: str, delivery: str) -> WebhookRequest:
    return WebhookRequest(
        headers={
            "X-GitHub-Event": event_name,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": _signature(body),
        },
        body=body,
    )


def _enqueue(gateway: GitHubWebhookGateway, fixture_name: str, *, event_name: str, delivery: str) -> None:
    response = gateway.handle(_request(fixture_name, event_name=event_name, delivery=delivery))
    assert response.status == 202
    assert response.correlation_id == delivery


def _enqueue_with_payload(
    gateway: GitHubWebhookGateway,
    payload: dict[str, object],
    *,
    event_name: str,
    delivery: str,
) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response = gateway.handle(_request_from_body(body, event_name=event_name, delivery=delivery))
    assert response.status == 202
    assert response.correlation_id == delivery


def _build_worker(
    *, aggregate_store: InMemoryPRAggregateStore, check_provider: MutableCheckSnapshotProvider
) -> tuple[Worker, RecordingOutputPoster]:
    def ci_feedback_for(event: PREvent) -> CIFeedbackContext:
        aggregate = aggregate_store.apply_pr_event(event)
        checks = check_provider.load(
            repo_full_name=event.repo_full_name,
            head_sha=aggregate.current_head_sha,
            correlation_id=event.meta.correlation_id,
        )
        readiness = aggregate.evaluate_readiness(current_check_snapshot=checks)
        return aggregate.to_ci_feedback_context(readiness=readiness, current_check_snapshot=checks)

    poster = RecordingOutputPoster()
    worker = Worker(
        orchestrator=EventOrchestrator(
            pr_orchestrator=PRWorkflowOrchestrator(ci_feedback_provider=ci_feedback_for),
            ci_orchestrator=CIWorkflowOrchestrator(aggregate_store=aggregate_store),
        ),
        output_poster=poster,
    )
    return worker, poster


def test_ci_completed_orphan_replay_fixture_stays_no_output_through_worker() -> None:
    queue = InMemoryJobQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    worker = Worker()

    _enqueue(
        gateway,
        "github_ci_completed_orphan_failure.json",
        event_name="workflow_run",
        delivery="delivery-ci-orphan-replay",
    )
    executions = worker.run_until_empty(queue)

    assert len(executions) == 1
    assert executions[0].status is WorkerStatus.SUCCEEDED
    assert executions[0].correlation_id == "delivery-ci-orphan-replay"
    result = executions[0].result
    assert result is not None
    assert isinstance(result.event, CICompleted)
    assert result.event.pr_number is None
    assert result.depth is CIWorkflowDepth.ORPHAN
    assert result.comment_payload is None


def test_ci_completed_fixture_replay_covers_linked_success_failure_and_orphan_cases() -> None:
    linked_success = parse_github_ci_event(
        _fixture_json("github_ci_completed_success.json"), correlation_id="replay-ci-success"
    )
    linked_failure = parse_github_ci_event(
        _fixture_json("github_ci_completed_failure.json"), correlation_id="replay-ci-failure"
    )
    orphan_failure = parse_github_ci_event(
        _fixture_json("github_ci_completed_orphan_failure.json"), correlation_id="replay-ci-orphan"
    )

    assert linked_success is not None
    assert linked_success.pr_number == 123
    assert linked_success.conclusion == "success"
    assert linked_success.failed_jobs == ()

    assert linked_failure is not None
    assert linked_failure.pr_number == 123
    assert linked_failure.conclusion == "failure"
    assert linked_failure.failed_jobs == ("test-integration", "lint-typecheck")

    assert orphan_failure is not None
    assert orphan_failure.pr_number is None
    assert orphan_failure.conclusion == "failure"
    assert orphan_failure.failed_jobs == ("qaestro-smoke",)


def test_ci_feedback_loop_replay_separates_pending_current_head_and_stale_history() -> None:
    queue = InMemoryJobQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    aggregate_store = InMemoryPRAggregateStore()
    check_provider = MutableCheckSnapshotProvider()
    worker, poster = _build_worker(aggregate_store=aggregate_store, check_provider=check_provider)

    check_provider.snapshots_by_head[OLD_HEAD_SHA] = (
        CheckRunSnapshot(
            name="CI Pipeline", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha=OLD_HEAD_SHA
        ),
    )
    _enqueue(gateway, "github_pr_opened.json", event_name="pull_request", delivery="delivery-pr-open")
    _enqueue(
        gateway,
        "github_ci_completed_stale_failure.json",
        event_name="workflow_run",
        delivery="delivery-ci-old-failure",
    )

    check_provider.snapshots_by_head[CURRENT_HEAD_SHA] = (
        CheckRunSnapshot(
            name="CI Pipeline", status=CheckRunStatus.IN_PROGRESS, conclusion=None, head_sha=CURRENT_HEAD_SHA
        ),
        CheckRunSnapshot(
            name="Security", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha=CURRENT_HEAD_SHA
        ),
    )
    pending_pr_payload = _fixture_json("github_pr_synchronize.json")
    pending_pr_payload["files"] = [
        {
            "filename": "src/middleware/auth_middleware.py",
            "status": "modified",
            "additions": 4,
            "deletions": 1,
        },
        {
            "filename": "src/api/auth.py",
            "status": "modified",
            "additions": 3,
            "deletions": 0,
        },
    ]
    _enqueue_with_payload(
        gateway,
        pending_pr_payload,
        event_name="pull_request",
        delivery="delivery-pr-sync-pending",
    )

    pending_executions = worker.run_until_empty(queue)

    assert [execution.status for execution in pending_executions] == [WorkerStatus.SUCCEEDED] * 3
    assert pending_executions[1].result is not None
    assert pending_executions[1].result.comment_payload is None
    assert poster.correlation_ids == ["delivery-pr-open", "delivery-pr-sync-pending"]
    assert poster.review_payloads[0] is not None
    assert poster.review_payloads[1] is None
    assert check_provider.calls == [
        ("acme-corp/web-api", OLD_HEAD_SHA, "delivery-pr-open"),
        ("acme-corp/web-api", CURRENT_HEAD_SHA, "delivery-pr-sync-pending"),
    ]

    pending_report = poster.payloads[-1].body
    assert "### CI / Check Feedback" in pending_report
    assert f"Current head: `{CURRENT_HEAD_SHA}`" in pending_report
    assert "Readiness: **WAITING FOR CHECKS**" in pending_report
    assert "Pending checks: `CI Pipeline`" in pending_report
    assert "Historical CI evidence from superseded heads" in pending_report
    assert f"`{OLD_HEAD_SHA}`" in pending_report
    assert "failed jobs: `test-integration`, `lint-typecheck`" in pending_report

    check_provider.snapshots_by_head[CURRENT_HEAD_SHA] = (
        CheckRunSnapshot(
            name="CI Pipeline", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha=CURRENT_HEAD_SHA
        ),
        CheckRunSnapshot(
            name="Security", status=CheckRunStatus.COMPLETED, conclusion="success", head_sha=CURRENT_HEAD_SHA
        ),
    )
    _enqueue(
        gateway,
        "github_ci_completed_success.json",
        event_name="workflow_run",
        delivery="delivery-ci-current-success",
    )
    _enqueue(gateway, "github_pr_synchronize.json", event_name="pull_request", delivery="delivery-pr-sync-final")

    final_executions = worker.run_until_empty(queue)

    assert [execution.status for execution in final_executions] == [WorkerStatus.SUCCEEDED] * 2
    assert final_executions[0].result is not None
    assert final_executions[0].result.comment_payload is None
    assert poster.correlation_ids == ["delivery-pr-open", "delivery-pr-sync-pending", "delivery-pr-sync-final"]
    assert poster.review_payloads[0] is not None
    assert poster.review_payloads[1] is None
    assert poster.review_payloads[-1] is not None
    assert check_provider.calls == [
        ("acme-corp/web-api", OLD_HEAD_SHA, "delivery-pr-open"),
        ("acme-corp/web-api", CURRENT_HEAD_SHA, "delivery-pr-sync-pending"),
        ("acme-corp/web-api", CURRENT_HEAD_SHA, "delivery-pr-sync-final"),
    ]

    final_report = poster.payloads[-1].body
    assert f"Current head: `{CURRENT_HEAD_SHA}`" in final_report
    assert "Readiness: **READY**" in final_report
    assert "Pending checks:" not in final_report
    assert "**CI Pipeline** — `success`" in final_report
    assert "Historical CI evidence from superseded heads" in final_report
    assert f"`{OLD_HEAD_SHA}`" in final_report
    assert "test-integration" in final_report

    aggregate = aggregate_store.get("acme-corp/web-api", 123)
    assert aggregate is not None
    readiness = aggregate.evaluate_readiness(current_check_snapshot=check_provider.snapshots_by_head[CURRENT_HEAD_SHA])
    feedback = aggregate.to_ci_feedback_context(
        readiness=readiness,
        current_check_snapshot=check_provider.snapshots_by_head[CURRENT_HEAD_SHA],
    )
    assert feedback.readiness is CIReadinessState.READY
    assert feedback.current_head_sha == CURRENT_HEAD_SHA
    assert [(item.workflow_name, item.conclusion, item.commit_sha) for item in feedback.current_observations] == [
        ("CI Pipeline", "success", CURRENT_HEAD_SHA),
        ("Security", "success", CURRENT_HEAD_SHA),
    ]
    assert len(feedback.historical_evidence) == 1
    assert feedback.historical_evidence[0].head_sha == OLD_HEAD_SHA
    assert feedback.historical_evidence[0].observations[0].conclusion == "failure"


def _fixture_json(name: str) -> dict[str, object]:
    import json

    payload: dict[str, object] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload
