"""Top-level event dispatch orchestration."""

from __future__ import annotations

from src.core.contracts import ChatMention, CICompleted, Event, PRCommented, PREvent, PRReviewed

from .chat_workflow import ChatWorkflowOrchestrator
from .ci_workflow import CIWorkflowOrchestrator, CIWorkflowResult
from .pr_event_stubs import PRCommentWorkflowOrchestrator, PRReviewWorkflowOrchestrator
from .pr_workflow import PRWorkflowOrchestrator
from .types import PRWorkflowResult, UnsupportedEventError


class EventOrchestrator:
    """Route normalized events to event-type-specific workflow orchestrators."""

    def __init__(
        self,
        *,
        pr_orchestrator: PRWorkflowOrchestrator | None = None,
        pr_comment_orchestrator: PRCommentWorkflowOrchestrator | None = None,
        pr_review_orchestrator: PRReviewWorkflowOrchestrator | None = None,
        ci_orchestrator: CIWorkflowOrchestrator | None = None,
        chat_orchestrator: ChatWorkflowOrchestrator | None = None,
    ) -> None:
        self._pr_orchestrator = pr_orchestrator or PRWorkflowOrchestrator()
        self._pr_comment_orchestrator = pr_comment_orchestrator or PRCommentWorkflowOrchestrator()
        self._pr_review_orchestrator = pr_review_orchestrator or PRReviewWorkflowOrchestrator()
        self._ci_orchestrator = ci_orchestrator or CIWorkflowOrchestrator()
        self._chat_orchestrator = chat_orchestrator or ChatWorkflowOrchestrator()

    def run(self, event: Event) -> PRWorkflowResult | CIWorkflowResult:
        if isinstance(event, PREvent):
            return self._pr_orchestrator.run(event)
        if isinstance(event, PRCommented):
            return self._pr_comment_orchestrator.run(event)
        if isinstance(event, PRReviewed):
            return self._pr_review_orchestrator.run(event)
        if isinstance(event, CICompleted):
            return self._ci_orchestrator.run(event)
        if isinstance(event, ChatMention):
            return self._chat_orchestrator.run(event)
        raise UnsupportedEventError(f"No workflow orchestrator registered for {type(event).__name__}")
