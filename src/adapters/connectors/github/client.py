"""Typed REST client for the small subset of GitHub endpoints qaestro uses.

Scope (Step 2):

- ``GET  /repos/{owner}/{repo}/pulls/{number}``                — :meth:`get_pull_request`
- ``GET  /repos/{owner}/{repo}/pulls/{number}/files``          — :meth:`list_pull_request_files`
- ``GET  /repos/{owner}/{repo}/pulls/{number}`` (diff accept)  — :meth:`get_pull_request_diff`
- ``POST /repos/{owner}/{repo}/issues/{number}/comments``      — :meth:`create_issue_comment`
- ``GET  /repos/{owner}/{repo}/issues/{number}/comments``      — :meth:`list_issue_comments`
- ``PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}`` — :meth:`update_issue_comment`

Out of scope: retries (worker handles), persistent token cache (in-memory only),
streaming, GraphQL.

The client is **stateless** beyond the auth + transport it holds, so a single
instance can be shared by multiple worker threads. The only mutable state lives
in :class:`GitHubAppAuth` and is already lock-protected.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from .auth import GitHubAppAuth
from .errors import AuthError, GitHubError, NotFoundError, RateLimitError
from .transport import HTTPResponse, HTTPTransport, UrllibTransport
from .types import CommentResult, FileDiff, PRMeta

# Page size for listing endpoints. Max allowed by GitHub is 100.
_DEFAULT_PER_PAGE = 100

# Hard cap to defend against degenerate PRs (1000s of files). Worker-tier
# pagination is fine, but we don't want a single connector call to spin
# forever on pathological inputs.
_MAX_PAGES = 30


def _segment(value: str) -> str:
    """URL-encode one path segment, including literal slashes."""
    return quote(value, safe="")


class GitHubClient:
    """Thin, typed wrapper over the GitHub REST API.

    Args:
        auth: Configured :class:`GitHubAppAuth`. Tokens are fetched on every
            call (cheap — cached internally).
        transport: HTTP transport. Defaults to :class:`UrllibTransport`.
        base_url: API root. Override for GitHub Enterprise.
        user_agent: Sent as ``User-Agent`` header. GitHub requires a non-empty
            value; defaults to ``qaestro``.
    """

    def __init__(
        self,
        *,
        auth: GitHubAppAuth,
        transport: HTTPTransport | None = None,
        base_url: str = "https://api.github.com",
        user_agent: str = "qaestro",
    ) -> None:
        self._auth = auth
        self._transport = transport or UrllibTransport()
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    # ── Public API ────────────────────────────────────────────────────

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta:
        """Fetch metadata for a single pull request."""
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls/{number}"
        resp = self._request("GET", path)
        data = resp.json()
        if not isinstance(data, dict):
            raise GitHubError("unexpected pull request payload shape")
        return _pr_meta_from_payload(data)

    def list_pull_request_files(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
    ) -> list[FileDiff]:
        """List all files changed in *number*, walking pagination eagerly."""
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")

        results: list[FileDiff] = []
        for page in range(1, _MAX_PAGES + 1):
            query = urlencode({"per_page": per_page, "page": page})
            path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls/{number}/files?{query}"
            resp = self._request("GET", path)
            page_data = resp.json()
            if not isinstance(page_data, list):
                raise GitHubError("unexpected pull request files payload shape")
            results.extend(_file_diff_from_payload(item) for item in page_data)
            if len(page_data) < per_page:
                break
        return results

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch the unified diff for a pull request."""
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls/{number}"
        resp = self._request(
            "GET",
            path,
            extra_headers={"Accept": "application/vnd.github.diff"},
        )
        return str(resp.text())

    def create_issue_comment(
        self,
        owner: str,
        repo: str,
        number: int,
        body: str,
    ) -> CommentResult:
        """Post a comment on an issue or pull request thread.

        GitHub treats PR conversation comments as issue comments — the same
        endpoint serves both.
        """
        if not body.strip():
            raise ValueError("comment body must not be empty")

        path = f"/repos/{_segment(owner)}/{_segment(repo)}/issues/{number}/comments"
        payload = json.dumps({"body": body}).encode("utf-8")
        resp = self._request(
            "POST",
            path,
            body=payload,
            extra_headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if not isinstance(data, dict):
            raise GitHubError("unexpected create-comment payload shape")
        return _comment_result_from_payload(data)

    def list_issue_comments(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
    ) -> list[CommentResult]:
        """List issue/PR conversation comments, walking pagination eagerly."""
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")

        results: list[CommentResult] = []
        for page in range(1, _MAX_PAGES + 1):
            query = urlencode({"per_page": per_page, "page": page})
            path = f"/repos/{_segment(owner)}/{_segment(repo)}/issues/{number}/comments?{query}"
            resp = self._request("GET", path)
            page_data = resp.json()
            if not isinstance(page_data, list):
                raise GitHubError("unexpected issue-comments payload shape")
            for item in page_data:
                if not isinstance(item, dict):
                    raise GitHubError("unexpected issue-comments payload shape")
                results.append(_comment_result_from_payload(item))
            if len(page_data) < per_page:
                break
        return results

    def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> CommentResult:
        """Update an existing issue/PR conversation comment."""
        if not body.strip():
            raise ValueError("comment body must not be empty")

        path = f"/repos/{_segment(owner)}/{_segment(repo)}/issues/comments/{comment_id}"
        payload = json.dumps({"body": body}).encode("utf-8")
        resp = self._request(
            "PATCH",
            path,
            body=payload,
            extra_headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if not isinstance(data, dict):
            raise GitHubError("unexpected update-comment payload shape")
        return _comment_result_from_payload(data)

    # ── Internal ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> HTTPResponse:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._auth.installation_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self._user_agent,
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = self._transport.request(method, url, headers=headers, body=body)
        _raise_for_status(resp)
        return resp


# ── Helpers ───────────────────────────────────────────────────────────────


def _raise_for_status(resp: HTTPResponse) -> None:
    if resp.status < 400:
        return

    detail = resp.text()[:200] if resp.body else ""
    if resp.status == 404:
        raise NotFoundError(f"not found: {detail}", status=404)
    if resp.status == 429:
        raise RateLimitError(
            f"rate limited: {detail}",
            status=429,
            reset_at=_int_header(_header(resp, "x-ratelimit-reset")),
        )
    if resp.status == 403 and _is_rate_limited(resp, detail):
        raise RateLimitError(
            f"rate limit exhausted: {detail}",
            status=403,
            reset_at=_int_header(_header(resp, "x-ratelimit-reset")),
        )
    if resp.status in (401, 403):
        raise AuthError(f"auth failed (status={resp.status}): {detail}", status=resp.status)
    raise GitHubError(f"github error (status={resp.status}): {detail}", status=resp.status)


def _header(resp: HTTPResponse, name: str) -> str | None:
    return resp.headers.get(name.lower())


def _is_rate_limited(resp: HTTPResponse, detail: str) -> bool:
    remaining = _header(resp, "x-ratelimit-remaining")
    if remaining == "0" or _header(resp, "retry-after") is not None:
        return True
    lowered = detail.lower()
    return "rate limit" in lowered or "abuse detection" in lowered


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _pr_meta_from_payload(data: dict[str, Any]) -> PRMeta:
    head = data.get("head") or {}
    base = data.get("base") or {}
    user = data.get("user") or {}
    return PRMeta(
        number=int(data.get("number", 0)),
        title=str(data.get("title", "")),
        state=str(data.get("state", "")),
        head_sha=str(head.get("sha", "")),
        base_ref=str(base.get("ref", "")),
        head_ref=str(head.get("ref", "")),
        author=str(user.get("login", "")),
        draft=bool(data.get("draft", False)),
        html_url=str(data.get("html_url", "")),
    )


def _comment_result_from_payload(data: dict[str, Any]) -> CommentResult:
    return CommentResult(
        id=int(data.get("id", 0)),
        html_url=str(data.get("html_url", "")),
        body=str(data.get("body", "")),
    )


def _file_diff_from_payload(data: dict[str, Any]) -> FileDiff:
    patch = data.get("patch")
    return FileDiff(
        filename=str(data.get("filename", "")),
        status=str(data.get("status", "")),
        additions=int(data.get("additions", 0)),
        deletions=int(data.get("deletions", 0)),
        changes=int(data.get("changes", 0)),
        patch=str(patch) if isinstance(patch, str) else None,
        previous_filename=str(data.get("previous_filename", "") or ""),
    )
