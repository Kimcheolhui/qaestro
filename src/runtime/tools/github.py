"""GitHub PR tool definitions backed by the existing GitHub Client API adapter."""

from __future__ import annotations

from typing import Protocol

from src.adapters.connectors.github import CommentResult, FileDiff, PRMeta

from . import ToolCall, ToolCapability, ToolDefinition


class GitHubPRToolClient(Protocol):
    """GitHub Client API subset required by PR read/write tools."""

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta: ...

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]: ...

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str: ...

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> CommentResult: ...

    def list_issue_comments(self, owner: str, repo: str, number: int) -> list[CommentResult]: ...

    def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> CommentResult: ...


def build_github_pr_tools(client: GitHubPRToolClient) -> tuple[ToolDefinition, ...]:
    """Expose narrow PR capabilities without exposing raw GitHubClient methods."""
    return (
        ToolDefinition(
            name="github.pr.view",
            capabilities=(ToolCapability.READ,),
            handler=lambda call: _get_pull_request(client, call),
        ),
        ToolDefinition(
            name="github.pr.files",
            capabilities=(ToolCapability.READ,),
            handler=lambda call: _list_pull_request_files(client, call),
        ),
        ToolDefinition(
            name="github.pr.diff",
            capabilities=(ToolCapability.READ,),
            handler=lambda call: _get_pull_request_diff(client, call),
        ),
        ToolDefinition(
            name="github.pr.comment.create_or_update",
            capabilities=(ToolCapability.WRITE,),
            handler=lambda call: _create_or_update_comment(client, call),
        ),
    )


def _get_pull_request(client: GitHubPRToolClient, call: ToolCall) -> PRMeta:
    owner, repo, pr_number = _repo_pr_input(call)
    return client.get_pull_request(owner, repo, pr_number)


def _list_pull_request_files(client: GitHubPRToolClient, call: ToolCall) -> tuple[FileDiff, ...]:
    owner, repo, pr_number = _repo_pr_input(call)
    return tuple(client.list_pull_request_files(owner, repo, pr_number))


def _get_pull_request_diff(client: GitHubPRToolClient, call: ToolCall) -> str:
    owner, repo, pr_number = _repo_pr_input(call)
    return client.get_pull_request_diff(owner, repo, pr_number)


def _create_or_update_comment(client: GitHubPRToolClient, call: ToolCall) -> CommentResult:
    owner, repo, pr_number = _repo_pr_input(call)
    body = str(call.input.get("body", ""))
    marker = str(call.input.get("marker", "")).strip()
    for comment in client.list_issue_comments(owner, repo, pr_number):
        if marker and marker in comment.body:
            return client.update_issue_comment(owner, repo, comment.id, body)
    return client.create_issue_comment(owner, repo, pr_number, body)


def _repo_pr_input(call: ToolCall) -> tuple[str, str, int]:
    repo_full_name = str(call.input.get("repo_full_name", ""))
    owner, repo = _split_repo(repo_full_name)
    return owner, repo, int(call.input.get("pr_number", 0))


def _split_repo(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"repo_full_name must be 'owner/repo', got {repo_full_name!r}")
    return parts[0], parts[1]
