"""CI-result feedback workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from src.adapters.renderers import PRCommentPayload
from src.core.contracts import CICompleted
from src.runtime.stages import WorkflowStage


class CIWorkflowDepth(StrEnum):
    """Workflow depth selected for a completed CI event."""

    ORPHAN = "orphan"
    LIGHTWEIGHT = "lightweight"
    NORMAL = "normal"
    DEEP = "deep"


@dataclass(frozen=True)
class CIWorkflowResult:
    """Traceable result for one CI feedback workflow run.

    Step 4 PR A intentionally keeps output side-effect free. Later Step 4
    slices will merge this result into the PR Behaviour Impact Report renderer.
    """

    event: CICompleted
    depth: CIWorkflowDepth
    summary: str
    stage_order: tuple[WorkflowStage, ...]
    comment_payload: PRCommentPayload | None = None

    @property
    def correlation_id(self) -> str:
        return self.event.meta.correlation_id


class CIContextProvider(Protocol):
    """Optional CI event enrichment seam used during context acquisition."""

    def load(self, event: CICompleted) -> CICompleted: ...


class CIWorkflowOrchestrator:
    """Classify completed CI events into linked/orphan feedback workflow results."""

    def __init__(self, *, context_provider: CIContextProvider | None = None) -> None:
        self._context_provider = context_provider

    def run(self, event: CICompleted) -> CIWorkflowResult:
        stages = (WorkflowStage.CONTEXT, WorkflowStage.TRIAGE)
        if event.pr_number is None:
            return CIWorkflowResult(
                event=event,
                depth=CIWorkflowDepth.ORPHAN,
                summary=(
                    "No pull request context is linked to this CI run; "
                    f"workflow {event.workflow_name!r} completed with {event.conclusion}."
                ),
                stage_order=stages,
            )

        event = self._context_provider.load(event) if self._context_provider is not None else event
        depth = _depth_for(event)
        failed_jobs = ", ".join(event.failed_jobs) if event.failed_jobs else "no failed jobs reported"
        return CIWorkflowResult(
            event=event,
            depth=depth,
            summary=(
                f"CI completed with {event.conclusion} for PR #{event.pr_number} "
                f"at {event.commit_sha}; failed jobs: {failed_jobs}."
            ),
            stage_order=stages,
        )


def _depth_for(event: CICompleted) -> CIWorkflowDepth:
    conclusion = event.conclusion.lower()
    if conclusion in {"failure", "timed_out"} or event.failed_jobs:
        return CIWorkflowDepth.DEEP
    if conclusion == "success":
        return CIWorkflowDepth.LIGHTWEIGHT
    return CIWorkflowDepth.NORMAL
