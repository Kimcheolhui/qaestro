"""End-to-end app-layer tests for webhook enqueueing and worker processing."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from src.adapters.renderers import PRCommentPayload
from src.app.gateway import GitHubWebhookGateway, WebhookRequest
from src.app.jobs import InMemoryJobQueue
from src.app.worker import Worker, WorkerStatus

FIXTURES = Path(__file__).parents[1] / "fixtures"
SECRET = "test-secret"


class RecordingCommentPoster:
    def __init__(self) -> None:
        self.payloads: list[PRCommentPayload] = []

    def post_comment(self, payload: PRCommentPayload) -> None:
        self.payloads.append(payload)


def _signature(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_github_webhook_job_runs_through_worker_and_posts_comment() -> None:
    body = (FIXTURES / "github_pr_opened.json").read_bytes()
    queue = InMemoryJobQueue()
    gateway = GitHubWebhookGateway(secret=SECRET, queue=queue)
    poster = RecordingCommentPoster()
    worker = Worker(comment_poster=poster)

    response = gateway.handle(
        WebhookRequest(
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-e2e-001",
                "X-Hub-Signature-256": _signature(body),
            },
            body=body,
        )
    )
    executions = worker.run_until_empty(queue)

    assert response.status == 202
    assert len(executions) == 1
    assert executions[0].status == WorkerStatus.SUCCEEDED
    assert executions[0].correlation_id == "delivery-e2e-001"
    assert len(poster.payloads) == 1
    assert poster.payloads[0].repo_full_name == "acme-corp/web-api"
    assert poster.payloads[0].pr_number == 123
    assert queue.dequeue() is None
