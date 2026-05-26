"""Evidence-backed Strategy Engine for Behaviour Impact Reports."""

from __future__ import annotations

from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    CIFeedbackContext,
    CIHistoricalEvidence,
    CIObservation,
    StrategyAction,
    StrategyResult,
)
from src.core.knowledge import InMemoryKnowledgeBase, KnowledgeBase, KnowledgeEntry, KnowledgeQuery


class EvidenceBackedPRStrategyEngine:
    """Strategy seam that exposes evidence without fabricating QA actions.

    Step 6.5 keeps deterministic CI/current-head normalization because it is
    observed evidence. Path groups, token-overlap knowledge hits, and numeric
    risk/confidence heuristics are not treated as executable recommendations;
    an agent/repo-knowledge-backed strategy planner should turn this context
    into product-facing validation actions later.
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
        actions = _ci_feedback_actions(ci_feedback)
        return StrategyResult(
            actions=actions,
            reasoning=_reasoning(impact, matches, ci_feedback),
            confidence=0.0,
            knowledge_refs=tuple(entry.key for entry in matches),
        )


# Backward-compatible import name while Step 7 agent-backed strategy planning is
# introduced. The implementation no longer emits rule/path-derived validation
# recommendations.
RuleBasedPRStrategyEngine = EvidenceBackedPRStrategyEngine


def _ci_feedback_actions(ci_feedback: CIFeedbackContext | None) -> tuple[StrategyAction, ...]:
    """Prioritize validation from observed current-head CI feedback only."""
    if ci_feedback is None:
        return ()
    actions: list[StrategyAction] = []
    for observation in ci_feedback.current_observations:
        conclusion = observation.conclusion.strip().lower()
        if conclusion not in {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}:
            continue
        actions.append(
            StrategyAction(
                action_type=ActionType.CUSTOM,
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
    return StrategyAction(
        action_type=ActionType.CUSTOM,
        description=f"Prioritize failed CI job '{job}' from workflow '{observation.workflow_name}'",
        target=f"ci:{observation.workflow_name}/{job}",
        priority=5,
        rationale="Current-head failed job is observed evidence and should drive validation priority.",
    )


def _reasoning(
    impact: BehaviourImpact,
    matches: tuple[KnowledgeEntry, ...],
    ci_feedback: CIFeedbackContext | None,
) -> str:
    path_groups = ", ".join(area.module for area in impact.areas) or "none"
    segments = [
        "Uncalibrated strategy context only; path groups and knowledge token matches are not executable recommendations.",
        f"Observed path groups: {path_groups}.",
    ]
    if matches:
        segments.append(f"Knowledge refs: {', '.join(entry.key for entry in matches)}.")
    if ci_feedback is not None:
        segments.append(_ci_reasoning(ci_feedback))
    return " ".join(segments)


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


def _query_text_from_title_and_impact(title: str, impact: BehaviourImpact) -> str:
    """Build the Step 3 free-text knowledge query from available PR facts."""
    files = " ".join(file for area in impact.areas for file in area.affected_files)
    path_groups = " ".join(area.module for area in impact.areas)
    return " ".join((title, impact.summary, path_groups, files))
