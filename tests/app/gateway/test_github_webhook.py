"""Tests for GitHub webhook gateway normalization and enqueueing."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from src.app.gateway import GitHubWebhookGateway, WebhookRequest
from src.app.worker import EventJob
from src.core.contracts import CICompleted, EventType, PROpened

FIXTURES = Path(__file__).parents[2] / "fixtures"
SECRET = "webhook-secret"


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[EventJob] = []

    def enqueue(self, job: EventJob) -> None:
        self.jobs.append(job)


def _body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _signature(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _request(event_name: str, body: bytes, *, delivery: str = "delivery-001") -> WebhookRequest:
    return WebhookRequest(
        headers={
            "X-GitHub-Event": event_name,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": _signature(body),
        },
        body=body,
    )


def test_valid_pull_request_opened_webhook_enqueues_normalized_pr_event() -> None:
    queue = RecordingQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    body = _body("github_pr_opened.json")

    response = gateway.handle(_request("pull_request", body, delivery="delivery-pr-001"))

    assert response.status == 202
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert isinstance(job.event, PROpened)
    assert job.event.meta.event_type == EventType.PR_OPENED
    assert job.event.meta.correlation_id == "delivery-pr-001"
    assert job.event.pr_number == 123
    assert job.event.repo_full_name == "acme-corp/web-api"


def test_valid_workflow_run_webhook_enqueues_normalized_ci_event() -> None:
    queue = RecordingQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    body = _body("github_ci_completed_success.json")

    response = gateway.handle(_request("workflow_run", body, delivery="delivery-ci-001"))

    assert response.status == 202
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert isinstance(job.event, CICompleted)
    assert job.event.meta.event_type == EventType.CI_COMPLETED
    assert job.event.meta.correlation_id == "delivery-ci-001"
    assert job.event.workflow_name == "CI Pipeline"
    assert job.event.run_id == 5551234567


def test_invalid_signature_rejects_without_enqueueing() -> None:
    queue = RecordingQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    body = _body("github_pr_opened.json")
    request = WebhookRequest(
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-bad",
            "X-Hub-Signature-256": "sha256=bad",
        },
        body=body,
    )

    response = gateway.handle(request)

    assert response.status == 401
    assert queue.jobs == []


def test_unhandled_webhook_action_is_accepted_without_enqueueing() -> None:
    queue = RecordingQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    payload = json.loads(_body("github_pr_opened.json"))
    payload["action"] = "labeled"
    body = json.dumps(payload).encode("utf-8")

    response = gateway.handle(_request("pull_request", body, delivery="delivery-ignored"))

    assert response.status == 204
    assert response.message == ""
    assert queue.jobs == []


def test_malformed_json_returns_bad_request_without_enqueueing() -> None:
    queue = RecordingQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    body = b"{not-json"

    response = gateway.handle(_request("pull_request", body))

    assert response.status == 400
    assert queue.jobs == []
