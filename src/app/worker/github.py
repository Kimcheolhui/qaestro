"""GitHub comment posting adapter used by the worker."""

from __future__ import annotations

from typing import Protocol

from src.adapters.renderers import PRCommentPayload


class GitHubIssueCommentClient(Protocol):
    """Subset of GitHubClient used by the worker comment poster."""

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> object: ...


class GitHubCommentPoster:
    """Post rendered PR comment payloads through :class:`GitHubClient`."""

    def __init__(self, client: GitHubIssueCommentClient) -> None:
        self._client = client

    def post_comment(self, payload: PRCommentPayload) -> None:
        owner, repo = _split_repo(payload.repo_full_name)
        self._client.create_issue_comment(owner, repo, payload.pr_number, payload.body)


def _split_repo(repo_full_name: str) -> tuple[str, str]:
    try:
        owner, repo = repo_full_name.split("/", 1)
    except ValueError as exc:
        raise ValueError(f"repo_full_name must be 'owner/repo', got {repo_full_name!r}") from exc
    if not owner or not repo:
        raise ValueError(f"repo_full_name must be 'owner/repo', got {repo_full_name!r}")
    return owner, repo
