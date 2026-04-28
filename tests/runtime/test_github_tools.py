"""Tests for GitHub PR tools exposed through ToolRuntime."""

from __future__ import annotations

import pytest

from src.adapters.connectors.github import ActionsJobResult, CommentResult, FileDiff, PRMeta
from src.adapters.renderers import PRCommentPayload
from src.runtime.orchestrator import ToolRuntimePRCommentPoster
from src.runtime.stages import WorkflowStage
from src.runtime.tools import RegisteredToolRuntime, StageToolPolicy, ToolCall
from src.runtime.tools.github import build_github_pr_tools


class RecordingGitHubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta:
        self.calls.append(("view", owner, repo, number))
        return PRMeta(
            number=number,
            title="feat: fetched",
            state="open",
            head_sha="abc123",
            base_ref="main",
            head_ref="feat/fetched",
            author="octocat",
            draft=False,
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}",
        )

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]:
        self.calls.append(("files", owner, repo, number))
        return [
            FileDiff(
                filename="src/app.py",
                status="modified",
                additions=10,
                deletions=2,
                changes=12,
                patch="@@",
            )
        ]

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        self.calls.append(("diff", owner, repo, number))
        return "diff --git a/src/app.py b/src/app.py"

    def list_workflow_run_jobs(self, owner: str, repo: str, run_id: int) -> list[ActionsJobResult]:
        self.calls.append(("actions_jobs", owner, repo, run_id))
        return [
            ActionsJobResult(
                name="tests",
                conclusion="failure",
                html_url="https://github.com/octocat/hello-world/actions/runs/99/job/1",
            ),
            ActionsJobResult(
                name="lint",
                conclusion="success",
                html_url="https://github.com/octocat/hello-world/actions/runs/99/job/2",
            ),
        ]

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> CommentResult:
        self.calls.append(("comment", owner, repo, number, body))
        return CommentResult(
            id=1234,
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}#issuecomment-1234",
            body=body,
        )

    def list_issue_comments(self, owner: str, repo: str, number: int) -> list[CommentResult]:
        self.calls.append(("comments", owner, repo, number))
        return []

    def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> CommentResult:
        self.calls.append(("update_comment", owner, repo, comment_id, body))
        return CommentResult(id=comment_id, html_url=f"https://github.com/{owner}/{repo}/pull/{comment_id}", body=body)


def _runtime(client: RecordingGitHubClient) -> RegisteredToolRuntime:
    return RegisteredToolRuntime(
        tools=build_github_pr_tools(client),
        policy=StageToolPolicy(
            {
                WorkflowStage.CONTEXT: ("github.pr.view", "github.pr.files", "github.pr.diff"),
                WorkflowStage.OUTPUT: ("github.pr.comment.create_or_update",),
            }
        ),
    )


def test_github_pr_read_tools_call_client_and_return_normalized_outputs() -> None:
    client = RecordingGitHubClient()
    runtime = _runtime(client)

    view = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.pr.view",
            input={"repo_full_name": "octocat/hello-world", "pr_number": 42},
            correlation_id="corr-gh",
        )
    )
    files = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.pr.files",
            input={"repo_full_name": "octocat/hello-world", "pr_number": 42},
            correlation_id="corr-gh",
        )
    )
    diff = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.pr.diff",
            input={"repo_full_name": "octocat/hello-world", "pr_number": 42},
            correlation_id="corr-gh",
        )
    )

    assert view.ok is True
    assert isinstance(view.output, PRMeta)
    assert view.output.title == "feat: fetched"
    assert files.ok is True
    assert files.output == (
        FileDiff(
            filename="src/app.py",
            status="modified",
            additions=10,
            deletions=2,
            changes=12,
            patch="@@",
        ),
    )
    assert diff.ok is True
    assert diff.output == "diff --git a/src/app.py b/src/app.py"
    assert client.calls == [
        ("view", "octocat", "hello-world", 42),
        ("files", "octocat", "hello-world", 42),
        ("diff", "octocat", "hello-world", 42),
    ]


def test_github_actions_jobs_tool_returns_failed_job_names_through_context_stage() -> None:
    client = RecordingGitHubClient()
    runtime = RegisteredToolRuntime(
        tools=build_github_pr_tools(client),
        policy=StageToolPolicy(
            {
                WorkflowStage.CONTEXT: ("github.actions.run.jobs",),
            }
        ),
    )

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.actions.run.jobs",
            input={"repo_full_name": "octocat/hello-world", "run_id": 99},
            correlation_id="corr-ci",
        )
    )

    assert result.ok is True
    assert result.output == (
        ActionsJobResult(
            name="tests",
            conclusion="failure",
            html_url="https://github.com/octocat/hello-world/actions/runs/99/job/1",
        ),
        ActionsJobResult(
            name="lint",
            conclusion="success",
            html_url="https://github.com/octocat/hello-world/actions/runs/99/job/2",
        ),
    )
    assert client.calls == [("actions_jobs", "octocat", "hello-world", 99)]


def test_github_actions_jobs_tool_requires_run_id() -> None:
    client = RecordingGitHubClient()
    runtime = RegisteredToolRuntime(
        tools=build_github_pr_tools(client),
        policy=StageToolPolicy({WorkflowStage.CONTEXT: ("github.actions.run.jobs",)}),
    )

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.actions.run.jobs",
            input={"repo_full_name": "octocat/hello-world"},
            correlation_id="corr-ci",
        )
    )

    assert result.ok is False
    assert "run_id is required" in result.error


def test_github_pr_comment_tool_posts_rendered_body() -> None:
    client = RecordingGitHubClient()
    runtime = _runtime(client)

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.OUTPUT,
            name="github.pr.comment.create_or_update",
            input={
                "repo_full_name": "octocat/hello-world",
                "pr_number": 42,
                "body": "Behaviour Impact Report",
            },
            correlation_id="corr-output",
        )
    )

    assert result.ok is True
    assert isinstance(result.output, CommentResult)
    assert result.output.id == 1234
    assert client.calls == [
        ("comments", "octocat", "hello-world", 42),
        ("comment", "octocat", "hello-world", 42, "Behaviour Impact Report"),
    ]


def test_github_pr_comment_tool_persists_marker_when_creating_comment() -> None:
    client = RecordingGitHubClient()
    runtime = _runtime(client)

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.OUTPUT,
            name="github.pr.comment.create_or_update",
            input={
                "repo_full_name": "octocat/hello-world",
                "pr_number": 42,
                "body": "Behaviour Impact Report",
                "marker": "qaestro-marker",
            },
            correlation_id="corr-output",
        )
    )

    assert result.ok is True
    assert client.calls == [
        ("comments", "octocat", "hello-world", 42),
        ("comment", "octocat", "hello-world", 42, "qaestro-marker\n\nBehaviour Impact Report"),
    ]


def test_github_pr_comment_tool_updates_existing_qaestro_comment_when_marker_matches() -> None:
    class ExistingCommentClient(RecordingGitHubClient):
        def list_issue_comments(self, owner: str, repo: str, number: int) -> list[CommentResult]:
            self.calls.append(("comments", owner, repo, number))
            return [
                CommentResult(
                    id=999,
                    html_url="https://github.com/octocat/hello-world/pull/42#issuecomment-999",
                    body="older report\nqaestro-marker",
                )
            ]

    client = ExistingCommentClient()
    runtime = _runtime(client)

    result = runtime.execute(
        ToolCall(
            stage=WorkflowStage.OUTPUT,
            name="github.pr.comment.create_or_update",
            input={
                "repo_full_name": "octocat/hello-world",
                "pr_number": 42,
                "body": "new Behaviour Impact Report",
                "marker": "qaestro-marker",
            },
            correlation_id="corr-output",
        )
    )

    assert result.ok is True
    assert isinstance(result.output, CommentResult)
    assert result.output.id == 999
    assert client.calls == [
        ("comments", "octocat", "hello-world", 42),
        ("update_comment", "octocat", "hello-world", 999, "qaestro-marker\n\nnew Behaviour Impact Report"),
    ]


def test_github_pr_tool_rejects_invalid_pr_number() -> None:
    client = RecordingGitHubClient()
    runtime = _runtime(client)

    for raw_pr_number in (None, "", 0, -1, "not-an-int"):
        input_payload: dict[str, object] = {"repo_full_name": "octocat/hello-world"}
        if raw_pr_number is not None:
            input_payload["pr_number"] = raw_pr_number
        result = runtime.execute(
            ToolCall(
                stage=WorkflowStage.CONTEXT,
                name="github.pr.view",
                input=input_payload,
                correlation_id="corr-gh",
            )
        )

        assert result.ok is False
        assert "pr_number" in result.error

    assert client.calls == []


def test_legacy_github_specific_adapters_are_not_exported_from_worker_api() -> None:
    import src.app.worker as worker_api

    assert not hasattr(worker_api, "GitHubCommentPoster")
    assert not hasattr(worker_api, "GitHubPRContextProvider")
    assert not hasattr(worker_api, "GitHubIssueCommentClient")
    assert not hasattr(worker_api, "GitHubPRContextClient")


def test_tool_runtime_output_poster_rejects_invalid_repo_full_name() -> None:
    client = RecordingGitHubClient()
    poster = ToolRuntimePRCommentPoster(_runtime(client))

    with pytest.raises(RuntimeError, match="repo_full_name"):
        poster.post_comment(
            PRCommentPayload(repo_full_name="invalid", pr_number=42, body="hello"), correlation_id="corr-output"
        )
