"""Tests for stdlib GitHub webhook HTTP endpoint wiring."""

from __future__ import annotations

from http.client import HTTPConnection
from threading import Thread

from src.app.gateway import create_github_webhook_server
from src.app.gateway.github import WebhookResponse


class RecordingGateway:
    def __init__(self, response: WebhookResponse | None = None) -> None:
        self.calls: list[tuple[dict[str, str], bytes]] = []
        self._response = response or WebhookResponse(status=202, message="ok", correlation_id="corr-http")

    def handle(self, request):
        self.calls.append((request.headers, request.body))
        return self._response


def test_github_webhook_server_exposes_post_endpoint() -> None:
    gateway = RecordingGateway()
    server = create_github_webhook_server(gateway, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request(
            "POST",
            "/webhooks/github",
            body=b'{"ok": true}',
            headers={"X-GitHub-Event": "pull_request"},
        )
        response = conn.getresponse()
        body = response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 202
    assert response.getheader("X-Qaestro-Correlation-Id") == "corr-http"
    assert body == b"ok"
    assert gateway.calls[0][0]["X-GitHub-Event"] == "pull_request"
    assert gateway.calls[0][1] == b'{"ok": true}'


def test_github_webhook_server_does_not_write_body_for_no_content_response() -> None:
    gateway = RecordingGateway(WebhookResponse(status=204, message="ignored", correlation_id="corr-http"))
    server = create_github_webhook_server(gateway, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("POST", "/webhooks/github", body=b'{"ok": true}')
        response = conn.getresponse()
        body = response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 204
    assert response.getheader("X-Qaestro-Correlation-Id") == "corr-http"
    assert body == b""
