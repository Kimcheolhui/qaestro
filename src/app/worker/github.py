"""GitHub comment posting and PR context adapters used by the worker."""

from __future__ import annotations

from typing import Protocol

from src.adapters.connectors.github import FileDiff, PRMeta
from src.adapters.renderers import PRCommentPayload
from src.core.analyzer import PRAnalysisContext, PRFileDiff
from src.core.contracts import PREvent


class GitHubIssueCommentClient(Protocol):
    """Subset of GitHubClient used by the worker comment poster."""

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> object: ...


class GitHubPRContextClient(Protocol):
    """GitHub client subset needed to enrich PR events for analysis."""

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta: ...

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]: ...

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str: ...


class GitHubCommentPoster:
    """Post rendered PR comment payloads through :class:`GitHubClient`."""

    def __init__(self, client: GitHubIssueCommentClient) -> None:
        self._client = client

    def post_comment(self, payload: PRCommentPayload) -> None:
        owner, repo = _split_repo(payload.repo_full_name)
        self._client.create_issue_comment(owner, repo, payload.pr_number, payload.body)


class GitHubPRContextProvider:
    """Fetch PR metadata, changed files, and unified diff via GitHub."""

    def __init__(self, client: GitHubPRContextClient) -> None:
        self._client = client

    def load(self, event: PREvent) -> PRAnalysisContext:
        owner, repo = _split_repo(event.repo_full_name)
        meta = self._client.get_pull_request(owner, repo, event.pr_number)
        files = self._client.list_pull_request_files(owner, repo, event.pr_number)
        unified_diff = self._client.get_pull_request_diff(owner, repo, event.pr_number)
        return PRAnalysisContext(
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            title=meta.title or event.title,
            body=event.body,
            base_branch=meta.base_ref or event.base_branch,
            head_branch=meta.head_ref or event.head_branch,
            files=tuple(_normalize_file(file) for file in files),
            unified_diff=unified_diff,
        )


def _normalize_file(file: FileDiff) -> PRFileDiff:
    return PRFileDiff(
        path=file.filename,
        status=file.status,
        additions=file.additions,
        deletions=file.deletions,
        patch=file.patch,
        previous_filename=file.previous_filename,
    )


def _split_repo(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"repo_full_name must be 'owner/repo', got {repo_full_name!r}")
    return parts[0], parts[1]
