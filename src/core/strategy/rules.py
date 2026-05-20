"""Rule-based Strategy Engine for Behaviour Impact Reports."""

from __future__ import annotations

from pathlib import PurePosixPath

from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    CIFeedbackContext,
    CIHistoricalEvidence,
    CIObservation,
    ImpactArea,
    RiskLevel,
    StrategyAction,
    StrategyResult,
)
from src.core.knowledge import InMemoryKnowledgeBase, KnowledgeBase, KnowledgeEntry, KnowledgeQuery


class RuleBasedPRStrategyEngine:
    """Deterministic strategy generator for Step 3.

    It converts analyzer facts into review/checklist actions. It does not run
    validation; runtime execution remains a later milestone.
    """

    def __init__(self, *, knowledge: KnowledgeBase | None = None) -> None:
        self._knowledge = knowledge or InMemoryKnowledgeBase()

    def plan(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        title: str,
        impact: BehaviourImpact,
        ci_feedback: CIFeedbackContext | None = None,
    ) -> StrategyResult:
        del pr_number
        matches = self._knowledge.search(
            KnowledgeQuery(
                repo_full_name=repo_full_name,
                query_text=_query_text_from_title_and_impact(title, impact),
            )
        )
        actions = (
            *_area_actions(impact),
            *_configuration_actions(impact),
            *_security_actions(impact),
            *_baseline_actions(impact),
            *_ci_feedback_actions(ci_feedback),
            *_knowledge_actions(matches),
        )
        return StrategyResult(
            actions=actions,
            reasoning=_reasoning(impact, matches, ci_feedback),
            confidence=_confidence(impact.overall_risk, matches, ci_feedback),
            knowledge_refs=tuple(entry.key for entry in matches),
        )


def _area_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    """Create one focused check suggestion per observed path group."""
    actions: list[StrategyAction] = []
    for area in impact.areas:
        if _is_low_signal_doc_group(area.module) or _is_configuration_group(area.module):
            continue
        target = _test_target_for_area(area)
        if target is None:
            continue
        actions.append(
            _action(
                action_type=ActionType.RUN_TESTS,
                description=_test_action_description(area),
                target=target,
                area=area,
                base_priority=2 if area.risk_level is RiskLevel.MEDIUM else 1,
            )
        )
    return tuple(actions)


def _baseline_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    actions: list[StrategyAction] = []
    executable_groups = {
        area.module
        for area in impact.areas
        if not _is_low_signal_doc_group(area.module)
        and not _is_configuration_group(area.module)
        and not _is_test_only_group(area)
    }
    if executable_groups:
        actions.append(
            StrategyAction(
                action_type=ActionType.RUN_TESTS,
                description="Run focused regression tests for changed behaviour",
                target="tests/",
                priority=2 if impact.overall_risk is RiskLevel.MEDIUM else 3 if _is_high(impact.overall_risk) else 1,
                rationale="Non-document path groups changed.",
            )
        )
    return tuple(actions)


def _knowledge_actions(matches: tuple[KnowledgeEntry, ...]) -> tuple[StrategyAction, ...]:
    actions: list[StrategyAction] = []
    for entry in matches:
        checklist = "; ".join(entry.checklist_items) or entry.summary
        actions.append(
            StrategyAction(
                action_type=ActionType.CUSTOM,
                description=f"Apply knowledge rule '{entry.key}': {checklist}",
                target=f"knowledge:{entry.key}",
                priority=4,
                rationale=entry.summary,
            )
        )
    return tuple(actions)


def _configuration_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    actions: list[StrategyAction] = []
    for area in impact.areas:
        if not _is_configuration_group(area.module):
            continue
        actions.append(
            StrategyAction(
                action_type=ActionType.CUSTOM,
                description="Review configuration or workflow changes for policy and runtime impact",
                target=f"config:{area.module}",
                priority=_review_priority(area.risk_level),
                rationale=f"Configuration-only path group changed: {_affected_files_text(area)}",
            )
        )
    return tuple(actions)


def _security_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    """Add explicit security review actions for security-sensitive changes."""
    actions: list[StrategyAction] = []
    for area in impact.areas:
        if _is_low_signal_doc_group(area.module) or not _is_security_sensitive_area(area):
            continue
        actions.append(
            StrategyAction(
                action_type=ActionType.CHECK_SECURITY,
                description="Review auth, credential, permission, or secret-handling changes",
                target=f"security:{area.module}",
                priority=4 if _is_high(area.risk_level) else 3,
                rationale=f"Security-sensitive signal observed in {area.module}: {_affected_files_text(area)}",
            )
        )
    return tuple(actions)


def _ci_feedback_actions(ci_feedback: CIFeedbackContext | None) -> tuple[StrategyAction, ...]:
    """Prioritize validation from current-head CI feedback.

    This deterministic mapping is a temporary strategy seam for Step 4. It uses
    observed current-head CI/check facts without diagnosing root cause; later
    Agent Framework + repository knowledge can replace the prioritization logic
    while preserving the CI feedback contract.
    """
    if ci_feedback is None:
        return ()
    actions: list[StrategyAction] = []
    for observation in ci_feedback.current_observations:
        conclusion = observation.conclusion.strip().lower()
        if conclusion not in {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}:
            continue
        actions.append(
            StrategyAction(
                action_type=ActionType.RUN_TESTS,
                description=f"Review current-head CI workflow '{observation.workflow_name}' result",
                target=f"ci:{observation.workflow_name}",
                priority=4 if conclusion in {"failure", "timed_out", "action_required", "startup_failure"} else 3,
                rationale=f"Current-head CI workflow concluded {conclusion}.",
            )
        )
        for job in observation.failed_jobs:
            actions.append(_ci_job_action(observation, job))
    return tuple(actions)


def _ci_job_action(observation: CIObservation, job: str) -> StrategyAction:
    action_type = _ci_job_action_type(job)
    return StrategyAction(
        action_type=action_type,
        description=f"Prioritize failed CI job '{job}' from workflow '{observation.workflow_name}'",
        target=f"ci:{observation.workflow_name}/{job}",
        priority=5,
        rationale="Current-head failed job is observed evidence and should drive validation priority.",
    )


def _ci_job_action_type(job: str) -> ActionType:
    normalized = job.strip().lower()
    if any(token in normalized for token in ("mypy", "pyright", "type")):
        return ActionType.TYPE_CHECK
    if any(token in normalized for token in ("lint", "ruff", "eslint", "flake")):
        return ActionType.RUN_LINTER
    if any(token in normalized for token in ("security", "sast", "secret", "bandit")):
        return ActionType.CHECK_SECURITY
    return ActionType.RUN_TESTS


def _action(
    *,
    action_type: ActionType,
    description: str,
    target: str,
    area: ImpactArea,
    base_priority: int,
) -> StrategyAction:
    priority = base_priority + (1 if _is_high(area.risk_level) else 0)
    return StrategyAction(
        action_type=action_type,
        description=description,
        target=target,
        priority=priority,
        rationale=_area_action_rationale(area),
    )


def _test_action_description(area: ImpactArea) -> str:
    if _is_test_only_group(area):
        return "Run the changed test target directly"
    return "Run focused tests or review checks for the observed path group"


def _area_action_rationale(area: ImpactArea) -> str:
    prefix = "Test-only path group" if _is_test_only_group(area) else f"{area.module} path group"
    return f"{prefix} is {area.risk_level.value} risk; affected files: {_affected_files_text(area)}"


def _affected_files_text(area: ImpactArea) -> str:
    return ", ".join(area.affected_files[:3]) or "none"


def _test_target_for_area(area: ImpactArea) -> str | None:
    module = area.module.strip("/")
    if not module:
        return None
    if _is_test_only_group(area):
        return module
    if module.startswith("src/"):
        return _test_target_for_src_module(module)
    return f"tests/{module}"


def _test_target_for_src_module(module: str) -> str:
    parts = PurePosixPath(module).parts
    if len(parts) == 1:
        return "tests/"
    if len(parts) >= 3 and parts[1] == "adapters" and parts[2] in {"connectors", "renderers"}:
        return "/".join(("tests", parts[1], parts[2]))
    if len(parts) >= 2 and parts[1] in {"app", "core", "runtime"}:
        return "/".join(("tests", parts[1]))
    return "/".join(("tests", *parts[1:]))


def _reasoning(
    impact: BehaviourImpact,
    matches: tuple[KnowledgeEntry, ...],
    ci_feedback: CIFeedbackContext | None,
) -> str:
    risk_label = impact.overall_risk.value.capitalize()
    path_groups = ", ".join(area.module for area in impact.areas) or "none"
    knowledge_text = f" Knowledge matches: {', '.join(entry.key for entry in matches)}." if matches else ""
    ci_text = f" {_ci_reasoning(ci_feedback)}" if ci_feedback is not None else ""
    return f"{risk_label} risk based on observed path groups: {path_groups}.{knowledge_text}{ci_text}"


def _ci_reasoning(ci_feedback: CIFeedbackContext) -> str:
    segments: list[str] = [f"source of truth: {ci_feedback.current_head_sha}."]
    if ci_feedback.current_observations:
        current = "; ".join(_observation_summary(observation) for observation in ci_feedback.current_observations)
        segments.append(f"current-head CI/check feedback: {current}.")
    if ci_feedback.pending_checks:
        segments.append(f"pending checks: {', '.join(ci_feedback.pending_checks)}.")
    historical = tuple(
        evidence
        for evidence in ci_feedback.historical_evidence
        if evidence.head_sha != ci_feedback.current_head_sha and evidence.observations
    )
    if historical:
        segments.append(
            "historical CI evidence on superseded heads: "
            + "; ".join(_historical_summary(evidence) for evidence in historical)
            + "."
        )
    return " ".join(segments)


def _observation_summary(observation: CIObservation) -> str:
    summary = f"{observation.workflow_name}={observation.conclusion.strip().lower()}"
    if observation.failed_jobs:
        summary += f" (failed jobs: {', '.join(observation.failed_jobs)})"
    return summary


def _historical_summary(evidence: CIHistoricalEvidence) -> str:
    return f"{evidence.head_sha}: " + ", ".join(
        _observation_summary(observation) for observation in evidence.observations
    )


def _confidence(
    risk: RiskLevel,
    matches: tuple[KnowledgeEntry, ...],
    ci_feedback: CIFeedbackContext | None,
) -> float:
    """Return the Step 4 placeholder confidence score.

    This is not a calibrated probability and must not be read as "qaestro is
    N% likely to be correct." The constants below are a deterministic
    evidence-strength heuristic used only to keep the current StrategyResult
    contract populated while the rule-based strategy engine is still a
    temporary implementation.

    Replacement direction:
    - Replace the hand-picked constants with a typed confidence/evidence model
      that records factors such as risk source, knowledge match strength, CI
      signal freshness, CI outcome severity, and missing-signal penalties.
    - Calibrate any numeric score from observed review/validation outcomes, or
      remove the numeric field from decision-making and expose the factors for
      policy ranking instead.
    - Keep a conservative cap or explicit uncertainty band if a future Agent
      Framework strategy engine still emits a scalar confidence value.
    """
    if _is_high(risk):
        # High-risk changes start lower because the rule-based engine has less
        # context than a real validation loop. This value is intentionally
        # arbitrary and should disappear when confidence is calibrated.
        base = 0.72
    elif risk is RiskLevel.MEDIUM:
        base = 0.76
    else:
        base = 0.82
    if matches:
        # Knowledge hits are treated as a weak positive signal for now; future
        # scoring should weight the relevance and historical reliability of the
        # matched rule instead of blindly adding a constant.
        base += 0.02
    if ci_feedback is not None and (ci_feedback.current_observations or ci_feedback.pending_checks):
        # CI/check feedback makes the strategy better grounded, but the current
        # rule does not distinguish fresh failures, pending checks, skipped jobs,
        # or flaky checks. A replacement should model those factors separately.
        base += 0.02
    return min(base, 0.9)


def _query_text_from_title_and_impact(title: str, impact: BehaviourImpact) -> str:
    """Build the Step 3 free-text knowledge query from available PR facts."""
    files = " ".join(file for area in impact.areas for file in area.affected_files)
    path_groups = " ".join(area.module for area in impact.areas)
    return " ".join((title, impact.summary, path_groups, files))


def _is_low_signal_doc_group(path_group: str) -> bool:
    normalized = path_group.strip("/").lower()
    if normalized in {"readme.md", "changelog.md", "contributing.md"}:
        return True
    return normalized == "docs" or normalized.startswith("docs/")


def _is_test_only_group(area: ImpactArea) -> bool:
    module = area.module.strip("/").lower()
    return module == "tests" or module.startswith("tests/")


def _is_configuration_group(path_group: str) -> bool:
    normalized = path_group.strip("/").lower()
    return normalized in {".github", ".github/workflows", "config", "infra"} or normalized.startswith(
        (".github/", "config/", "infra/")
    )


def _is_security_sensitive_area(area: ImpactArea) -> bool:
    haystack = " ".join((area.module, area.description, " ".join(area.affected_files))).lower()
    return any(
        signal in haystack
        for signal in (
            "auth",
            "credential",
            "permission",
            "private_key",
            "secret",
            "signature",
            "token",
            "webhook",
        )
    )


def _review_priority(risk: RiskLevel) -> int:
    if _is_high(risk):
        return 4
    if risk is RiskLevel.MEDIUM:
        return 2
    return 1


def _is_high(risk: RiskLevel) -> bool:
    return risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
