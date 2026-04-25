"""GitHub webhook gateway request handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.adapters.connectors.github import verify_signature
from src.core.contracts import Event
from src.core.contracts.parsers import (
    parse_github_ci_event,
    parse_github_comment_event,
    parse_github_pr_event,
    parse_github_pr_review_event,
)
from src.shared import new_correlation_id, set_correlation_id

from ..jobs import EnqueueQueue, EventJob


@dataclass(frozen=True)
class WebhookRequest:
    """Raw webhook request data needed by the gateway."""

    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class WebhookResponse:
    """Small transport-agnostic response returned by the gateway."""

    status: int
    message: str = ""
    correlation_id: str = ""


class GitHubWebhookGateway:
    """Verify, normalize, and enqueue GitHub webhook deliveries."""

    def __init__(self, *, secret: str, queue: EnqueueQueue) -> None:
        self._secret = secret
        self._queue = queue

    def handle(self, request: WebhookRequest) -> WebhookResponse:
        headers = _normalise_headers(request.headers)
        signature = headers.get("x-hub-signature-256")
        if not verify_signature(self._secret, request.body, signature):
            return WebhookResponse(status=401, message="invalid signature")

        correlation_id = _correlation_id(headers)
        set_correlation_id(correlation_id)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return WebhookResponse(status=400, message="invalid json", correlation_id=correlation_id)

        if not isinstance(payload, dict):
            return WebhookResponse(status=400, message="payload must be a JSON object", correlation_id=correlation_id)

        event = _parse_event(headers.get("x-github-event", ""), payload, correlation_id)
        if event is None:
            return WebhookResponse(status=204, correlation_id=correlation_id)

        self._queue.enqueue(EventJob(event=event, correlation_id=correlation_id))
        return WebhookResponse(status=202, message="enqueued", correlation_id=correlation_id)


def _normalise_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _correlation_id(headers: dict[str, str]) -> str:
    return headers.get("x-github-delivery") or new_correlation_id()


def _parse_event(event_name: str, payload: dict[str, Any], correlation_id: str) -> Event | None:
    action = str(payload.get("action", ""))
    if event_name == "pull_request":
        return parse_github_pr_event(payload, action=action, correlation_id=correlation_id)
    if event_name == "workflow_run":
        return parse_github_ci_event(payload, correlation_id=correlation_id)
    if event_name == "pull_request_review":
        return parse_github_pr_review_event(payload, correlation_id=correlation_id)
    if event_name in {"issue_comment", "pull_request_review_comment"}:
        return parse_github_comment_event(payload, correlation_id=correlation_id)
    return None
