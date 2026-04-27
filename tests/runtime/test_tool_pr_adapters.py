"""Tests for ToolRuntime-backed PR workflow context/output adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from src.adapters.connectors.github import CommentResult, FileDiff, PRMeta
from src.adapters.renderers import PRCommentPayload
from src.core.contracts import EventMeta, EventSource, EventType, PROpened
from src.runtime.orchestrator import ToolRuntimePRCommentPoster, ToolRuntimePRContextProvider
from src.runtime.tools import ToolAuditEntry, ToolCall, ToolResult


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self.outputs = {
            "github.pr.view": PRMeta(
                number=77,
                title="feat: runtime tools",
                state="open",
                head_sha="abc123",
                base_ref="main",
                head_ref="feat/tools",
                author="octocat",
                draft=False,
                html_url="https://github.com/octocat/hello-world/pull/77",
            ),
            "github.pr.files": (
                FileDiff(
                    filename="src/runtime/tools/__init__.py",
                    status="added",
                    additions=50,
                    deletions=0,
                    changes=50,
                    patch="@@",
                ),
            ),
            "github.pr.diff": "diff --git a/src/runtime/tools/__init__.py b/src/runtime/tools/__init__.py",
            "github.pr.comment.create_or_update": CommentResult(
                id=9876,
                html_url="https://github.com/octocat/hello-world/pull/77#issuecomment-9876",
            ),
        }

    @property
    def audit_log(self) -> tuple[ToolAuditEntry, ...]:
        return ()

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call=call, ok=True, output=self.outputs[call.name])


def _event() -> PROpened:
    return PROpened(
        meta=EventMeta(
            event_id="evt-tools",
            event_type=EventType.PR_OPENED,
            correlation_id="corr-tools",
            timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=UTC),
            source=EventSource.GITHUB,
        ),
        repo_full_name="octocat/hello-world",
        pr_number=77,
        title="feat: webhook title",
        body="Webhook body",
        author="octocat",
        base_branch="main",
        head_branch="feat/webhook",
        diff_url="https://github.com/octocat/hello-world/pull/77.diff",
    )


def test_tool_runtime_pr_context_provider_collects_context_via_context_stage_tools() -> None:
    runtime = RecordingRuntime()

    context = ToolRuntimePRContextProvider(runtime).load(_event())

    assert context.title == "feat: runtime tools"
    assert context.head_branch == "feat/tools"
    assert context.files[0].path == "src/runtime/tools/__init__.py"
    assert context.unified_diff.startswith("diff --git")
    assert [(call.stage, call.name, call.correlation_id) for call in runtime.calls] == [
        ("context", "github.pr.view", "corr-tools"),
        ("context", "github.pr.files", "corr-tools"),
        ("context", "github.pr.diff", "corr-tools"),
    ]


def test_tool_runtime_pr_comment_poster_posts_via_output_stage_tool() -> None:
    runtime = RecordingRuntime()
    payload = PRCommentPayload(repo_full_name="octocat/hello-world", pr_number=77, body="report body")

    result = ToolRuntimePRCommentPoster(runtime).post_comment(payload, correlation_id="corr-tools")
    marker = "Repository: `octocat/hello-world`\nPull request: `#77`"

    assert result.id == 9876
    assert [(call.stage, call.name, call.input, call.correlation_id) for call in runtime.calls] == [
        (
            "output",
            "github.pr.comment.create_or_update",
            {"repo_full_name": "octocat/hello-world", "pr_number": 77, "body": "report body", "marker": marker},
            "corr-tools",
        )
    ]
