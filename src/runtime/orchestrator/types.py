"""Shared orchestration data contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.adapters.renderers import PRCommentPayload
from src.core.analyzer import PRAnalysisContext
from src.core.contracts import BehaviourImpact, PREvent, QAReport, StrategyResult, ValidationResult
from src.runtime.stages import WorkflowStage


class UnsupportedEventError(RuntimeError):
    """Raised when an event has no supported workflow orchestration yet."""


@dataclass(frozen=True)
class PRWorkflowDraft:
    """Pre-render output of a PR workflow run.

    The draft is passed to PR renderers before channel-specific payloads exist.
    Keeping this separate from :class:`PRWorkflowResult` avoids placeholder
    payloads and makes the renderer contract explicit.
    """

    event: PREvent
    report: QAReport
    stage_order: tuple[WorkflowStage, ...]

    @property
    def correlation_id(self) -> str:
        return self.event.meta.correlation_id

    @property
    def impact(self) -> BehaviourImpact:
        return self.report.impact

    @property
    def strategy(self) -> StrategyResult:
        return self.report.strategy

    @property
    def validations(self) -> tuple[ValidationResult, ...]:
        return self.report.validations


@dataclass(frozen=True)
class PRWorkflowResult:
    """Traceable final output of one PR workflow run."""

    event: PREvent
    report: QAReport
    comment_payload: PRCommentPayload
    stage_order: tuple[WorkflowStage, ...]

    @property
    def correlation_id(self) -> str:
        return self.event.meta.correlation_id

    @property
    def impact(self) -> BehaviourImpact:
        return self.report.impact

    @property
    def strategy(self) -> StrategyResult:
        return self.report.strategy

    @property
    def validations(self) -> tuple[ValidationResult, ...]:
        return self.report.validations


class PRWorkflowRenderer(Protocol):
    """Renderer contract used by the PR workflow."""

    def render(self, draft: PRWorkflowDraft) -> PRCommentPayload: ...


class PRBehaviourAnalyzer(Protocol):
    """Analyze normalized PR context into behaviour impact output."""

    def analyze(self, context: PRAnalysisContext) -> BehaviourImpact: ...


class PRStrategyEngine(Protocol):
    """Choose PR workflow strategy actions from analysed impact."""

    def plan(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        title: str,
        impact: BehaviourImpact,
    ) -> StrategyResult: ...


class PRRuntimeValidator(Protocol):
    """Validate planned PR workflow strategy actions."""

    def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]: ...


ShouldValidate = Callable[[PREvent, BehaviourImpact, StrategyResult], bool]
