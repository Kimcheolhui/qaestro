"""Tests for :class:`GitHubClient` — endpoints, errors, pagination."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import cast

import pytest

from src.adapters.connectors.github import GitHubAppAuth, GitHubClient
from src.adapters.connectors.github.errors import (
    AuthError,
    GitHubError,
    NotFoundError,
    RateLimitError,
)
from src.adapters.connectors.github.transport import FakeResponse, FakeTransport, UrllibTransport

APP_ID = 12345
INSTALL_ID = 99999
OWNER = "octocat"
REPO = "hello-world"
PR_NUM = 42

TOKEN_URL = f"https://api.github.com/app/installations/{INSTALL_ID}/access_tokens"


class ManualClock:
    def __init__(self) -> None:
        self._t = 1_700_000_000.0

    def now(self) -> float:
        return self._t


def _token_response() -> FakeResponse:
    base = datetime.fromtimestamp(1_700_000_000.0, tz=UTC)
    expires = base + timedelta(seconds=3600)
    body = json.dumps({"token": "ghs_test", "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}).encode()
    return FakeResponse(status=201, body=body)


@pytest.fixture
def private_key(github_app_private_key_pem: bytes) -> str:
    return github_app_private_key_pem.decode()


@pytest.fixture
def transport() -> FakeTransport:
    t = FakeTransport()
    t.route("POST", TOKEN_URL, _token_response())
    return t


@pytest.fixture
def client(private_key: str, transport: FakeTransport) -> GitHubClient:
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    return GitHubClient(auth=auth, transport=transport)


# ── get_pull_request ─────────────────────────────────────────────────────


def test_get_pull_request_returns_meta(client, transport):
    pr_payload = {
        "number": PR_NUM,
        "title": "Add feature X",
        "state": "open",
        "draft": False,
        "html_url": f"https://github.com/{OWNER}/{REPO}/pull/{PR_NUM}",
        "user": {"login": "alice"},
        "head": {"sha": "deadbeef", "ref": "feature/x"},
        "base": {"ref": "main"},
    }
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=200, body=json.dumps(pr_payload).encode()),
    )

    meta = client.get_pull_request(OWNER, REPO, PR_NUM)
    assert meta.number == PR_NUM
    assert meta.title == "Add feature X"
    assert meta.state == "open"
    assert meta.head_sha == "deadbeef"
    assert meta.base_ref == "main"
    assert meta.head_ref == "feature/x"
    assert meta.author == "alice"
    assert meta.draft is False


def test_get_pull_request_sets_required_headers(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(
            status=200,
            body=b'{"number":42,"title":"t","state":"open","head":{"sha":"x","ref":"y"},"base":{"ref":"main"},"user":{"login":"a"},"draft":false,"html_url":""}',
        ),
    )
    client.get_pull_request(OWNER, REPO, PR_NUM)
    # First call is the token exchange, second is the actual API call.
    api_call = next(c for c in transport.calls if "/pulls/" in c.url)
    assert api_call.headers["Authorization"] == "Bearer ghs_test"
    assert api_call.headers["Accept"] == "application/vnd.github+json"
    assert api_call.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert api_call.headers["User-Agent"] == "qaestro"


def test_owner_and_repo_are_encoded_as_path_segments(client, transport):
    owner = "bad/owner"
    repo = "repo with space/slash"
    transport.route(
        "GET",
        f"https://api.github.com/repos/bad%2Fowner/repo%20with%20space%2Fslash/pulls/{PR_NUM}",
        FakeResponse(
            status=200,
            body=b'{"number":42,"title":"t","state":"open","head":{"sha":"x","ref":"y"},"base":{"ref":"main"},"user":{"login":"a"},"draft":false,"html_url":""}',
        ),
    )

    meta = client.get_pull_request(owner, repo, PR_NUM)

    assert meta.number == PR_NUM


# ── list_pull_request_files (pagination) ─────────────────────────────────


def test_list_pull_request_files_handles_pagination(client, transport):
    page1 = [
        {"filename": f"a{i}.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": "@@"}
        for i in range(100)
    ]
    page2 = [{"filename": "b.py", "status": "added", "additions": 5, "deletions": 0, "changes": 5, "patch": "@@"}]
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}/files?per_page=100&page=1",
        FakeResponse(status=200, body=json.dumps(page1).encode()),
    )
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}/files?per_page=100&page=2",
        FakeResponse(status=200, body=json.dumps(page2).encode()),
    )

    files = client.list_pull_request_files(OWNER, REPO, PR_NUM)
    assert len(files) == 101
    assert files[0].filename == "a0.py"
    assert files[-1].filename == "b.py"
    assert files[-1].status == "added"
    assert files[-1].additions == 5


def test_list_pull_request_files_short_first_page_stops(client, transport):
    page1 = [{"filename": "x.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": None}]
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}/files?per_page=100&page=1",
        FakeResponse(status=200, body=json.dumps(page1).encode()),
    )
    files = client.list_pull_request_files(OWNER, REPO, PR_NUM)
    assert len(files) == 1
    # Make sure it didn't fetch page 2
    assert not any("page=2" in c.url for c in transport.calls)


def test_list_pull_request_files_handles_binary(client, transport):
    page1 = [{"filename": "logo.png", "status": "added", "additions": 0, "deletions": 0, "changes": 0}]
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}/files?per_page=100&page=1",
        FakeResponse(status=200, body=json.dumps(page1).encode()),
    )
    files = client.list_pull_request_files(OWNER, REPO, PR_NUM)
    assert files[0].patch is None


def test_list_pull_request_files_preserves_previous_filename_for_renames(client, transport):
    page1 = [
        {
            "filename": "new.py",
            "previous_filename": "old.py",
            "status": "renamed",
            "additions": 2,
            "deletions": 1,
            "changes": 3,
            "patch": "@@",
        }
    ]
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}/files?per_page=100&page=1",
        FakeResponse(status=200, body=json.dumps(page1).encode()),
    )

    files = client.list_pull_request_files(OWNER, REPO, PR_NUM)

    assert files[0].previous_filename == "old.py"


def test_list_pull_request_files_validates_per_page(client):
    with pytest.raises(ValueError):
        client.list_pull_request_files(OWNER, REPO, PR_NUM, per_page=0)
    with pytest.raises(ValueError):
        client.list_pull_request_files(OWNER, REPO, PR_NUM, per_page=101)


# ── get_pull_request_diff ────────────────────────────────────────────────


def test_get_pull_request_diff_uses_diff_accept_header(client, transport):
    diff_text = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-old\n+new\n"
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=200, body=diff_text.encode()),
    )
    out = client.get_pull_request_diff(OWNER, REPO, PR_NUM)
    assert out == diff_text
    api_call = next(c for c in transport.calls if "/pulls/" in c.url)
    assert api_call.headers["Accept"] == "application/vnd.github.diff"


# ── create_issue_comment ─────────────────────────────────────────────────


def test_create_issue_comment_posts_body(client, transport):
    transport.route(
        "POST",
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUM}/comments",
        FakeResponse(
            status=201,
            body=json.dumps({"id": 555, "html_url": "https://github.com/x/comments/555"}).encode(),
        ),
    )
    result = client.create_issue_comment(OWNER, REPO, PR_NUM, "hello")
    assert result.id == 555
    assert result.html_url.endswith("/555")

    api_call = next(c for c in transport.calls if "/issues/" in c.url)
    assert api_call.method == "POST"
    assert json.loads(api_call.body) == {"body": "hello"}
    assert api_call.headers["Content-Type"] == "application/json"


def test_create_issue_comment_rejects_empty_body(client):
    with pytest.raises(ValueError):
        client.create_issue_comment(OWNER, REPO, PR_NUM, "   ")


# ── error mapping ────────────────────────────────────────────────────────


def test_404_raises_not_found(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=404, body=b'{"message":"Not Found"}'),
    )
    with pytest.raises(NotFoundError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)
    assert ei.value.status == 404


def test_401_raises_auth_error(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=401, body=b'{"message":"Bad credentials"}'),
    )
    with pytest.raises(AuthError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)
    assert ei.value.status == 401


def test_403_with_remaining_zero_raises_rate_limit(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(
            status=403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000999"},
            body=b'{"message":"API rate limit exceeded"}',
        ),
    )
    with pytest.raises(RateLimitError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)
    assert ei.value.status == 403
    assert ei.value.reset_at == 1700000999


def test_403_with_retry_after_raises_rate_limit(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(
            status=403,
            headers={"Retry-After": "30"},
            body=b'{"message":"You have exceeded a secondary rate limit"}',
        ),
    )

    with pytest.raises(RateLimitError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)

    assert ei.value.status == 403
    assert ei.value.reset_at is None


def test_403_without_rate_limit_header_raises_auth_error(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=403, body=b'{"message":"forbidden"}'),
    )
    with pytest.raises(AuthError):
        client.get_pull_request(OWNER, REPO, PR_NUM)


def test_429_raises_rate_limit(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(
            status=429,
            headers={"x-ratelimit-reset": "1700000999"},
            body=b'{"message":"Too many"}',
        ),
    )
    with pytest.raises(RateLimitError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)
    assert ei.value.status == 429
    assert ei.value.reset_at == 1700000999


def test_500_raises_generic_github_error(client, transport):
    transport.route(
        "GET",
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUM}",
        FakeResponse(status=500, body=b"server boom"),
    )
    with pytest.raises(GitHubError) as ei:
        client.get_pull_request(OWNER, REPO, PR_NUM)
    assert ei.value.status == 500
    assert not isinstance(ei.value, (NotFoundError, AuthError, RateLimitError))


def test_urllib_transport_does_not_follow_redirects_with_authorization():
    seen_count = 0
    seen_path = ""
    seen_authorization: str | None = None

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal seen_authorization, seen_count, seen_path

            seen_count += 1
            if not seen_path:
                seen_path = self.path
            if seen_authorization is None:
                seen_authorization = self.headers.get("Authorization")
            self.send_response(302)
            host, port = cast(tuple[str, int], self.server.server_address)
            self.send_header("Location", f"http://{host}:{port}/leak")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        resp = UrllibTransport().request(
            "GET",
            f"http://127.0.0.1:{server.server_address[1]}/start",
            headers={"Authorization": "Bearer secret"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert resp.status == 302
    assert seen_count == 1
    assert seen_path == "/start"
    assert seen_authorization == "Bearer secret"
