"""Webhook receiver and event normalizer.

Implementation lives in focused modules under this package. ``__init__`` only
re-exports the public gateway API and console-script entrypoint.
"""

from __future__ import annotations

from ..jobs import EnqueueQueue, EventJob, InMemoryJobQueue, JobQueue
from .entrypoint import main
from .github import GitHubWebhookGateway, WebhookRequest, WebhookResponse
from .server import WebhookHandler, create_github_webhook_server, make_github_webhook_handler, serve_github_webhook

__all__ = [
    "EnqueueQueue",
    "EventJob",
    "GitHubWebhookGateway",
    "InMemoryJobQueue",
    "JobQueue",
    "WebhookHandler",
    "WebhookRequest",
    "WebhookResponse",
    "create_github_webhook_server",
    "main",
    "make_github_webhook_handler",
    "serve_github_webhook",
]
