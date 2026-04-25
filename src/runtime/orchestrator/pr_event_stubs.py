"""PR comment/review workflow orchestration stubs."""

from __future__ import annotations

from src.core.contracts import PRCommented, PRReviewed

from .types import PRWorkflowResult, UnsupportedEventError


class PRCommentWorkflowOrchestrator:
    """Placeholder for PR comment-triggered orchestration.

    Step 2 only runs the PR opened/updated workflow. Comment-triggered follow-up
    behavior is routed explicitly here so PRCommented events do not look
    accidentally unsupported.
    """

    def run(self, event: PRCommented) -> PRWorkflowResult:
        raise UnsupportedEventError(
            "PR comment workflow orchestration is planned for a later milestone "
            f"and is not implemented yet: {event.repo_full_name}#{event.pr_number} comment {event.comment_id}"
        )


class PRReviewWorkflowOrchestrator:
    """Placeholder for PR review-triggered orchestration.

    Step 2 only runs the PR opened/updated workflow. Review-triggered follow-up
    behavior is routed explicitly here so PRReviewed events do not look
    accidentally unsupported.
    """

    def run(self, event: PRReviewed) -> PRWorkflowResult:
        raise UnsupportedEventError(
            "PR review workflow orchestration is planned for a later milestone "
            f"and is not implemented yet: {event.repo_full_name}#{event.pr_number} review {event.state}"
        )
