"""CI-result feedback workflow orchestration stub."""

from __future__ import annotations

from src.core.contracts import CICompleted

from .types import PRWorkflowResult, UnsupportedEventError


class CIWorkflowOrchestrator:
    """Placeholder for CI-result feedback orchestration."""

    def run(self, event: CICompleted) -> PRWorkflowResult:
        raise UnsupportedEventError(
            "CI workflow orchestration is planned for a later milestone "
            f"and is not implemented yet: {event.workflow_name}"
        )
