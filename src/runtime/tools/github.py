"""GitHub PR tool definitions backed by the existing GitHub Client API adapter."""

from __future__ import annotations

from typing import Protocol

from src.adapters.connectors.github import ActionsJobResult, CheckRunResult, CommentResult, FileDiff, PRMeta

from . import ToolCall, ToolCapability, ToolDefinition


class GitHubPRToolClient(Protocol):
    """GitHub Client API subset required by PR read/write tools."""

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta: ...

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]: ...

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str: ...

    def list_workflow_run_jobs(self, owner: str, repo: str, run_id: int) -> list[ActionsJobResult]: ...

    def list_check_runs_for_ref(self, owner: str, repo: str, ref: str) -> list[CheckRunResult]: ...

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
            name="github.actions.run.jobs",
            capabilities=(ToolCapability.READ,),
            handler=lambda call: _list_workflow_run_jobs(client, call),
        ),
        ToolDefinition(
            name="github.checks.runs_for_ref",
            capabilities=(ToolCapability.READ,),
            handler=lambda call: _list_check_runs_for_ref(client, call),
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


def _list_workflow_run_jobs(client: GitHubPRToolClient, call: ToolCall) -> tuple[ActionsJobResult, ...]:
    owner, repo = _repo_input(call)
    raw_run_id = call.input.get("run_id")
    if raw_run_id is None or raw_run_id == "":
        raise ValueError("run_id is required and must be a positive integer")
    try:
        run_id = int(raw_run_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("run_id must be a positive integer") from exc
    if run_id <= 0:
        raise ValueError("run_id must be greater than 0")
    return tuple(client.list_workflow_run_jobs(owner, repo, run_id))


def _list_check_runs_for_ref(client: GitHubPRToolClient, call: ToolCall) -> tuple[CheckRunResult, ...]:
    owner, repo = _repo_input(call)
    ref = str(call.input.get("ref", "")).strip()
    if not ref:
        raise ValueError("ref is required")
    return tuple(client.list_check_runs_for_ref(owner, repo, ref))


def _create_or_update_comment(client: GitHubPRToolClient, call: ToolCall) -> CommentResult:
    owner, repo, pr_number = _repo_pr_input(call)
    body = str(call.input.get("body", ""))
    marker = str(call.input.get("marker", "")).strip()
    persisted_body = _persisted_comment_body(body, marker)
    for comment in client.list_issue_comments(owner, repo, pr_number):
        if marker and marker in comment.body:
            return client.update_issue_comment(owner, repo, comment.id, persisted_body)
    return client.create_issue_comment(owner, repo, pr_number, persisted_body)


def _persisted_comment_body(body: str, marker: str) -> str:
    if not marker or marker in body:
        return body
    if not body:
        return marker
    return f"{marker}\n\n{body}"


def _repo_input(call: ToolCall) -> tuple[str, str]:
    repo_full_name = str(call.input.get("repo_full_name", ""))
    return _split_repo(repo_full_name)


def _repo_pr_input(call: ToolCall) -> tuple[str, str, int]:
    repo_full_name = str(call.input.get("repo_full_name", ""))
    owner, repo = _split_repo(repo_full_name)
    raw_pr_number = call.input.get("pr_number")
    if raw_pr_number is None or raw_pr_number == "":
        raise ValueError("pr_number is required and must be a positive integer")
    try:
        pr_number = int(raw_pr_number)
    except (TypeError, ValueError) as exc:
        raise ValueError("pr_number must be a positive integer") from exc
    if pr_number <= 0:
        raise ValueError("pr_number must be greater than 0")
    return owner, repo, pr_number


def _split_repo(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"repo_full_name must be 'owner/repo', got {repo_full_name!r}")
    return parts[0], parts[1]
