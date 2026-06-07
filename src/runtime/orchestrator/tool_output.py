"""ToolRuntime-backed PR output posting."""

from __future__ import annotations

from dataclasses import dataclass

from src.adapters.connectors.github import CommentResult, PRMeta, ReviewResult
from src.adapters.renderers import PRCommentPayload, PRReviewPayload
from src.runtime.stages import WorkflowStage
from src.runtime.tools import ToolCall, ToolRuntime
from src.shared.redaction import redact_text


@dataclass(frozen=True)
class PROutputPostResult:
    """External side effects produced by PR output posting."""

    comment: CommentResult | None = None
    review: ReviewResult | None = None


class ToolRuntimePROutputPoster:
    """Post managed summary comments and optional official reviews via output tools."""

    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def post_outputs(
        self,
        comment_payload: PRCommentPayload,
        *,
        review_payload: PRReviewPayload | None = None,
        correlation_id: str,
    ) -> PROutputPostResult:
        prepared_review = None
        existing_review = None
        if review_payload is not None:
            prepared_review = self._prepare_review(review_payload, correlation_id=correlation_id)
            existing_review = self._preflight_review(prepared_review, correlation_id=correlation_id)
        comment = ToolRuntimePRCommentPoster(self._runtime).post_comment(comment_payload, correlation_id=correlation_id)
        review = existing_review
        if prepared_review is not None and review is None:
            review = self._create_review(prepared_review, correlation_id=correlation_id)
        return PROutputPostResult(comment=comment, review=review)

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> CommentResult:
        return ToolRuntimePRCommentPoster(self._runtime).post_comment(payload, correlation_id=correlation_id)

    def post_review(self, payload: PRReviewPayload, *, correlation_id: str) -> ReviewResult:
        prepared = self._prepare_review(payload, correlation_id=correlation_id)
        existing = self._preflight_review(prepared, correlation_id=correlation_id)
        if existing is not None:
            return existing
        return self._create_review(prepared, correlation_id=correlation_id)

    def _prepare_review(self, payload: PRReviewPayload, *, correlation_id: str) -> PRReviewPayload:
        prepared = payload.prepared_for_submission()
        return prepared.with_correlation_id(correlation_id)

    def _preflight_review(self, prepared: PRReviewPayload, *, correlation_id: str) -> ReviewResult | None:
        self._ensure_current_head(prepared, correlation_id=correlation_id)
        return self._find_existing_review(prepared, correlation_id=correlation_id)

    def _create_review(self, prepared: PRReviewPayload, *, correlation_id: str) -> ReviewResult:
        result = self._runtime.execute(
            ToolCall(
                stage=WorkflowStage.OUTPUT,
                name="github.pr.review.create",
                input={
                    "repo_full_name": prepared.repo_full_name,
                    "pr_number": prepared.pr_number,
                    "head_sha": prepared.head_sha,
                    "body": prepared.body,
                    "event": prepared.event,
                    "comments": tuple(
                        {
                            "path": comment.path,
                            "body": comment.body,
                            "line": comment.line,
                            "side": comment.side,
                            **({"start_line": comment.start_line} if comment.start_line is not None else {}),
                            **({"start_side": comment.start_side} if comment.start_line is not None else {}),
                        }
                        for comment in prepared.comments
                    ),
                },
                correlation_id=correlation_id,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or "github.pr.review.create failed")
        if not isinstance(result.output, ReviewResult):
            raise TypeError("github.pr.review.create returned unexpected output type")
        return result.output

    def _ensure_current_head(self, payload: PRReviewPayload, *, correlation_id: str) -> None:
        result = self._runtime.execute(
            ToolCall(
                stage=WorkflowStage.OUTPUT,
                name="github.pr.view",
                input={"repo_full_name": payload.repo_full_name, "pr_number": payload.pr_number},
                correlation_id=correlation_id,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or "github.pr.view failed")
        current_head = _head_sha_from_output(result.output)
        if current_head != payload.head_sha:
            raise RuntimeError(f"stale head for PR review: expected {current_head}, got {payload.head_sha}")

    def _find_existing_review(self, payload: PRReviewPayload, *, correlation_id: str) -> ReviewResult | None:
        result = self._runtime.execute(
            ToolCall(
                stage=WorkflowStage.OUTPUT,
                name="github.pr.review.list",
                input={"repo_full_name": payload.repo_full_name, "pr_number": payload.pr_number},
                correlation_id=correlation_id,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or "github.pr.review.list failed")
        reviews = result.output
        if not isinstance(reviews, tuple):
            raise TypeError("github.pr.review.list returned unexpected output type")
        for review in reviews:
            if not isinstance(review, ReviewResult):
                raise TypeError("github.pr.review.list returned unexpected output type")
            if review.commit_id == payload.head_sha and correlation_id in review.body:
                return review
        return None


class ToolRuntimePRCommentPoster:
    """Post rendered PR comments through the output-stage GitHub write tool."""

    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def post_comment(self, payload: PRCommentPayload, *, correlation_id: str) -> CommentResult:
        result = self._runtime.execute(
            ToolCall(
                stage=WorkflowStage.OUTPUT,
                name="github.pr.comment.create_or_update",
                input={
                    "repo_full_name": payload.repo_full_name,
                    "pr_number": payload.pr_number,
                    "body": redact_text(payload.body, redact_urls=True),
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


def _head_sha_from_output(output: object) -> str:
    if isinstance(output, PRMeta):
        return output.head_sha
    if isinstance(output, dict):
        return str(output.get("head_sha", ""))
    raise TypeError("github.pr.view returned unexpected output type")


def _qaestro_comment_marker(repo_full_name: str, pr_number: int) -> str:
    return f"Repository: `{repo_full_name}`\nPull request: `#{pr_number}`"
