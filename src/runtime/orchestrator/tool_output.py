"""ToolRuntime-backed PR output posting."""

from __future__ import annotations

from src.adapters.connectors.github import CommentResult
from src.adapters.renderers import PRCommentPayload
from src.runtime.tools import ToolCall, ToolRuntime


class ToolRuntimePRCommentPoster:
    """Post rendered PR comments through the output-stage GitHub write tool."""

    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> CommentResult:
        result = self._runtime.execute(
            ToolCall(
                stage="output",
                name="github.pr.comment.create_or_update",
                input={
                    "repo_full_name": payload.repo_full_name,
                    "pr_number": payload.pr_number,
                    "body": payload.body,
                    "marker": _qaestro_comment_marker(payload.repo_full_name, payload.pr_number),
                },
                correlation_id=correlation_id,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or "github.pr.comment.create_or_update failed")
        if not isinstance(result.output, CommentResult):
            raise TypeError("github.pr.comment.create_or_update returned unexpected output type")
        return result.output


def _qaestro_comment_marker(repo_full_name: str, pr_number: int) -> str:
    return f"Repository: `{repo_full_name}`\nPull request: `#{pr_number}`"
