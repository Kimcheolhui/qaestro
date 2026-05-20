"""PR workflow triage and depth-selection policies."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

from src.core.analyzer import PRAnalysisContext, PRFileDiff, PRFileStatus
from src.runtime.agent import AgentRunInput, AgentRunStatus, AgentSessionHandle, AgentSessionScope
from src.runtime.agent.types import AgentRunner
from src.runtime.prompts import PromptId, load_prompt
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


class AgentBackedPRWorkflowTriageClassifier:
    """Agent Runtime-backed PR intent/depth classifier with conservative fallback.

    The classifier asks the Agent Runtime to judge workflow depth from PR intent,
    risk, and repository context rather than treating path categories such as
    docs-only/config-only/test-only as perfect rules. The deterministic fallback
    remains a safety net for unavailable or malformed agent responses.
    """

    def __init__(
        self,
        *,
        runner: AgentRunner,
        fallback: RuleBasedPRWorkflowTriageClassifier | None = None,
        max_turns: int = 1,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._runner = runner
        self._fallback = fallback or RuleBasedPRWorkflowTriageClassifier()
        self._max_turns = max_turns
        self._timeout_seconds = timeout_seconds

    def classify(self, context: PRAnalysisContext) -> PRWorkflowTriage:
        fallback = self._fallback.classify(context)
        session_handle = _triage_session_handle(context)
        session = session_handle
        try:
            session = self._runner.start_session(session_handle)
            result = self._runner.run(
                session=session,
                run_input=AgentRunInput(
                    stage=WorkflowStage.TRIAGE,
                    prompt=load_prompt(PromptId.PR_WORKFLOW_TRIAGE).text,
                    correlation_id=session.correlation_id,
                    context=_agent_triage_context(context),
                    max_turns=self._max_turns,
                    max_tool_calls=0,
                    timeout_seconds=self._timeout_seconds,
                ),
            )
        except Exception as exc:
            return _fallback_triage(fallback, f"agent_runner_exception: {_safe_error(exc)}")
        finally:
            with suppress(Exception):
                self._runner.close_session(session, reason="triage stage complete")

        if result.status is not AgentRunStatus.SUCCEEDED:
            return _fallback_triage(fallback, f"agent_runner_status: {result.status.value}")

        try:
            return _triage_from_agent_output(result.output_text)
        except ValueError as exc:
            return _fallback_triage(fallback, f"invalid_agent_output: {_safe_error(exc)}")


def _triage_session_handle(context: PRAnalysisContext) -> AgentSessionHandle:
    return AgentSessionHandle(
        session_id=f"triage-{_safe_session_part(context.repo_full_name)}-{context.pr_number}",
        scope=AgentSessionScope.STAGE,
        repo_full_name=context.repo_full_name,
        pr_number=context.pr_number,
        head_sha="unknown",
        trigger="triage",
        correlation_id=f"triage-{context.repo_full_name}-{context.pr_number}",
    )


def _agent_triage_context(context: PRAnalysisContext) -> Mapping[str, object]:
    return {
        "repo_full_name": context.repo_full_name,
        "pr_number": context.pr_number,
        "title": context.title,
        "body": context.body,
        "base_branch": context.base_branch,
        "head_branch": context.head_branch,
        "changed_lines": sum(file.additions + file.deletions for file in context.files),
        "files": tuple(_file_summary(file) for file in context.files),
        "unified_diff_excerpt": context.unified_diff[:8000],
    }


def _file_summary(file: PRFileDiff) -> Mapping[str, object]:
    summary: dict[str, object] = {
        "path": file.path,
        "status": file.status.value,
        "additions": file.additions,
        "deletions": file.deletions,
    }
    if file.previous_filename:
        summary["previous_filename"] = file.previous_filename
    if file.patch:
        summary["patch_excerpt"] = file.patch[:1200]
    return summary


def _triage_from_agent_output(output_text: str) -> PRWorkflowTriage:
    data = _json_object_from_text(output_text)
    depth = _parse_depth(data.get("depth"))
    rationale = str(data.get("rationale") or "Agent triage selected workflow depth.").strip()
    if not rationale:
        rationale = "Agent triage selected workflow depth."
    allowed_stages = _parse_allowed_stages(data.get("allowed_stages"), depth)
    return PRWorkflowTriage(depth=depth, rationale=rationale, allowed_stages=allowed_stages)


def _json_object_from_text(output_text: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", output_text, flags=re.DOTALL)
        if match is None:
            raise ValueError("agent output did not contain a JSON object") from exc
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, Mapping):
        raise ValueError("agent output JSON must be an object")
    return parsed


def _parse_depth(value: object) -> PRWorkflowDepth:
    try:
        return PRWorkflowDepth(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unsupported triage depth: {value!r}") from exc


def _parse_allowed_stages(value: object, depth: PRWorkflowDepth) -> tuple[WorkflowStage, ...]:
    if value is None:
        return _default_allowed_stages(depth)
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError("allowed_stages must be a list of stage names")
    stages: list[WorkflowStage] = []
    for item in value:
        try:
            stage = WorkflowStage(str(item).strip().lower())
        except ValueError as exc:
            raise ValueError(f"unsupported allowed stage: {item!r}") from exc
        if stage not in (WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR):
            raise ValueError(f"triage cannot allow workflow stage: {stage.value}")
        stages.append(stage)
    return tuple(dict.fromkeys(stages))


def _default_allowed_stages(depth: PRWorkflowDepth) -> tuple[WorkflowStage, ...]:
    if depth in (PRWorkflowDepth.NORMAL, PRWorkflowDepth.DEEP):
        return (WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR)
    return ()


def _fallback_triage(fallback: PRWorkflowTriage, reason: str) -> PRWorkflowTriage:
    return PRWorkflowTriage(
        depth=fallback.depth,
        rationale=f"Agent triage unavailable ({reason}); fallback used: {fallback.rationale}",
        allowed_stages=fallback.allowed_stages,
    )


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:160] or exc.__class__.__name__


def _safe_session_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "repo"


_LOW_SIGNAL_ROOT_FILES = {"readme.md", "changelog.md", "license", "notice"}
_LOW_SIGNAL_DIRS = {"docs"}
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
        return False
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
    # Temporary seam hygiene only: match whole path/text tokens so short signals
    # like "api" and "auth" do not fire on unrelated words such as "capital"
    # or "author". This is not a permanent programmatic PR-depth classifier.
    observed_tokens = set(re.split(r"[^a-z0-9]+", "\n".join(haystacks).lower()))
    return any(token in observed_tokens for token in _DEEP_SIGNAL_TOKENS)


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
