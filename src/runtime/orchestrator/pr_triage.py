"""PR workflow triage and depth-selection policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.core.analyzer import PRAnalysisContext, PRFileStatus
from src.runtime.stages import WorkflowStage


class PRWorkflowDepth(StrEnum):
    """Workflow depth selected after PR context acquisition."""

    NOOP = "noop"
    LIGHTWEIGHT = "lightweight"
    NORMAL = "normal"
    DEEP = "deep"


@dataclass(frozen=True)
class PRWorkflowTriage:
    """Audit record describing why a PR uses a given workflow depth.

    Step 3.5 keeps this classifier deterministic as a temporary policy seam.
    This must be replaced by Agent Framework + repo knowledge/instruction based
    classification while preserving this bounded workflow contract and stage
    allowlist result. Programmatic path/token heuristics are not expected to be
    the final PR intent/depth decision model.
    """

    depth: PRWorkflowDepth
    rationale: str
    allowed_stages: tuple[WorkflowStage, ...]

    @property
    def runs_analysis(self) -> bool:
        return WorkflowStage.ANALYZER in self.allowed_stages

    @property
    def runs_strategy(self) -> bool:
        return WorkflowStage.STRATEGY in self.allowed_stages

    @property
    def allows_validation(self) -> bool:
        return WorkflowStage.VALIDATOR in self.allowed_stages

    @property
    def renders_output(self) -> bool:
        return self.depth is not PRWorkflowDepth.NOOP


class RuleBasedPRWorkflowTriageClassifier:
    """Deterministic placeholder for PR intent/depth classification.

    This is intentionally conservative and portable. It only chooses a
    lightweight path for very small, low-signal documentation/metadata changes,
    escalates obvious high-impact signals to deep, and otherwise preserves the
    normal Step 3 analysis path. It is only a temporary seam and must be replaced
    by Agent Framework + repo-knowledge/instruction based classification.
    """

    def classify(self, context: PRAnalysisContext) -> PRWorkflowTriage:
        if _requires_deep_workflow(context):
            return PRWorkflowTriage(
                depth=PRWorkflowDepth.DEEP,
                rationale="High-impact change signals require full analysis and validation.",
                allowed_stages=(WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR),
            )
        if _is_lightweight_change(context):
            return PRWorkflowTriage(
                depth=PRWorkflowDepth.LIGHTWEIGHT,
                rationale="Small low-signal documentation or metadata change; full analysis was skipped.",
                allowed_stages=(),
            )
        return PRWorkflowTriage(
            depth=PRWorkflowDepth.NORMAL,
            rationale="Default PR workflow depth; run behaviour analysis and strategy planning.",
            allowed_stages=(WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR),
        )


_LOW_SIGNAL_ROOT_FILES = {"readme.md", "changelog.md", "license", "notice"}
_LOW_SIGNAL_DIRS = {"docs", ".github"}
_DEEP_SIGNAL_TOKENS = (
    "api",
    "auth",
    "authorization",
    "breaking",
    "deploy",
    "deployment",
    "migration",
    "permission",
    "runbook",
    "secret",
    "security",
)
_GENERATED_PATH_PARTS = {"generated", "dist", "build"}


def _is_lightweight_change(context: PRAnalysisContext) -> bool:
    """Return true for tiny low-signal changes safe for summary-only output."""
    if not context.files:
        return True
    changed_lines = sum(file.additions + file.deletions for file in context.files)
    if changed_lines > 30 or len(context.files) > 5:
        return False
    return all(_is_low_signal_file(file.path) for file in context.files) and not _contains_deep_signal(context)


def _requires_deep_workflow(context: PRAnalysisContext) -> bool:
    """Escalate obvious semantic or risky signals without path taxonomies."""
    if any(file.status is PRFileStatus.REMOVED for file in context.files):
        return True
    changed_lines = sum(file.additions + file.deletions for file in context.files)
    if changed_lines >= 250:
        return True
    return _contains_deep_signal(context)


def _contains_deep_signal(context: PRAnalysisContext) -> bool:
    haystacks = [context.title, context.body, context.unified_diff]
    haystacks.extend(file.path for file in context.files)
    haystacks.extend(file.patch or "" for file in context.files)
    lowered = "\n".join(haystacks).lower()
    return any(token in lowered for token in _DEEP_SIGNAL_TOKENS)


def _is_low_signal_file(path: str) -> bool:
    normalized = path.strip("/").lower()
    if not normalized:
        return True
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts:
        return True
    if any(part in _GENERATED_PATH_PARTS for part in parts):
        return True
    if len(parts) == 1:
        return parts[0] in _LOW_SIGNAL_ROOT_FILES or parts[0].endswith((".md", ".rst", ".txt"))
    return parts[0] in _LOW_SIGNAL_DIRS
