"""ChatOps workflow orchestration stub."""

from __future__ import annotations

from src.core.contracts import ChatMention

from .types import PRWorkflowResult, UnsupportedEventError


class ChatWorkflowOrchestrator:
    """Placeholder for ChatOps orchestration."""

    def run(self, event: ChatMention) -> PRWorkflowResult:
        raise UnsupportedEventError(
            "Chat workflow orchestration is planned for a later milestone "
            f"and is not implemented yet: {event.platform}:{event.channel_id}"
        )
