"""Stdlib HTTP endpoint for GitHub webhooks."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

from .github import WebhookRequest, WebhookResponse

_GITHUB_WEBHOOK_PATH = "/webhooks/github"


class WebhookHandler(Protocol):
    """Gateway surface required by the HTTP transport."""

    def handle(self, request: WebhookRequest) -> WebhookResponse: ...


def make_github_webhook_handler(gateway: WebhookHandler) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to a configured gateway instance."""

    class GitHubWebhookHTTPHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != _GITHUB_WEBHOOK_PATH:
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            response = gateway.handle(
                WebhookRequest(
                    headers={key: value for key, value in self.headers.items()},
                    body=body,
                )
            )
            self.send_response(response.status)
            if response.correlation_id:
                self.send_header("X-Qaestro-Correlation-Id", response.correlation_id)
            self.end_headers()
            if response.message and response.status not in {204, 304}:
                self.wfile.write(response.message.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            # Suppress stdlib access-log writes. Application logging should be
            # attached around the transport when deployment wiring is added.
            return None

    return GitHubWebhookHTTPHandler


def create_github_webhook_server(
    gateway: WebhookHandler,
    *,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    """Create a stdlib HTTP server exposing ``POST /webhooks/github``."""

    return ThreadingHTTPServer((host, port), make_github_webhook_handler(gateway))


def serve_github_webhook(gateway: WebhookHandler, *, host: str, port: int) -> None:
    """Serve the GitHub webhook endpoint until interrupted."""

    server = create_github_webhook_server(gateway, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
