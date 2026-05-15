"""Rule-based Strategy Engine for Behaviour Impact Reports."""

from __future__ import annotations

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
    return tuple(
        _action(
            action_type=ActionType.RUN_TESTS,
            description="Run focused tests or review checks for the observed path group",
            target=f"tests/{area.module}",
            area=area,
            base_priority=2 if area.risk_level is RiskLevel.MEDIUM else 1,
        )
        for area in impact.areas
        if not _is_low_signal_doc_group(area.module)
    )


def _baseline_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    actions: list[StrategyAction] = []
    executable_groups = {area.module for area in impact.areas if not _is_low_signal_doc_group(area.module)}
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
    files = ", ".join(area.affected_files[:3])
    return StrategyAction(
        action_type=action_type,
        description=description,
        target=target,
        priority=priority,
        rationale=f"{area.module} path group is {area.risk_level.value} risk; affected files: {files}",
    )


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
    return path_group.lower() in {"readme.md", "docs", "changelog.md"}


def _is_high(risk: RiskLevel) -> bool:
    return risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
