"""Rule-based Strategy Engine for Behaviour Impact Reports."""

from __future__ import annotations

from src.core.contracts import ActionType, BehaviourImpact, ImpactArea, RiskLevel, StrategyAction, StrategyResult
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
    ) -> StrategyResult:
        del pr_number
        matches = self._knowledge.search(
            KnowledgeQuery(
                repo_full_name=repo_full_name,
                domains=tuple(area.module for area in impact.areas),
                terms=_terms_from_title_and_impact(title, impact),
            )
        )
        actions = (*_area_actions(impact), *_baseline_actions(impact), *_knowledge_actions(matches))
        return StrategyResult(
            actions=actions,
            reasoning=_reasoning(impact, matches),
            confidence=_confidence(impact.overall_risk, matches),
            knowledge_refs=tuple(entry.key for entry in matches),
        )


def _area_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    actions: list[StrategyAction] = []
    for area in impact.areas:
        if area.module == "api":
            actions.append(
                _action(
                    action_type=ActionType.VERIFY_API_CONTRACT,
                    description="Verify API contract and backwards-compatible request/response behaviour",
                    target="api",
                    area=area,
                    base_priority=3,
                )
            )
        elif area.module == "ui":
            actions.append(
                _action(
                    action_type=ActionType.SMOKE_TEST,
                    description="Smoke test the affected UI flow in the changed surface",
                    target="ui",
                    area=area,
                    base_priority=3,
                )
            )
        elif area.module == "config":
            actions.append(
                _action(
                    action_type=ActionType.SMOKE_TEST,
                    description="Verify configuration loads in the target environment",
                    target="config",
                    area=area,
                    base_priority=3,
                )
            )
        elif area.module == "infra":
            actions.append(
                _action(
                    action_type=ActionType.CUSTOM,
                    description="Review deployment or infrastructure plan before rollout",
                    target="infra",
                    area=area,
                    base_priority=3,
                )
            )
        else:
            actions.append(
                _action(
                    action_type=ActionType.RUN_TESTS,
                    description="Run focused tests or review checks for the affected module",
                    target=f"tests/{area.module}",
                    area=area,
                    base_priority=1,
                )
            )
    return tuple(actions)


def _baseline_actions(impact: BehaviourImpact) -> tuple[StrategyAction, ...]:
    modules = {area.module for area in impact.areas}
    actions: list[StrategyAction] = []
    executable_modules = {area.module for area in impact.areas if area.module not in {"docs", "tests"}}
    if executable_modules:
        actions.append(
            StrategyAction(
                action_type=ActionType.RUN_TESTS,
                description="Run focused regression tests for changed behaviour",
                target="tests/",
                priority=2 if impact.overall_risk is RiskLevel.MEDIUM else 3 if _is_high(impact.overall_risk) else 1,
                rationale="Executable source or behaviour-facing files changed.",
            )
        )
    if modules & {"config", "infra"}:
        actions.append(
            StrategyAction(
                action_type=ActionType.RUN_LINTER,
                description="Run lint/static validation for configuration and deployment files",
                target=".",
                priority=2 if _is_high(impact.overall_risk) else 1,
                rationale="Configuration or infrastructure files changed.",
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
        rationale=f"{area.module} area is {area.risk_level.value} risk; affected files: {files}",
    )


def _reasoning(impact: BehaviourImpact, matches: tuple[KnowledgeEntry, ...]) -> str:
    risk_label = impact.overall_risk.value.capitalize()
    modules = ", ".join(area.module for area in impact.areas) or "none"
    knowledge_text = f" Knowledge matches: {', '.join(entry.key for entry in matches)}." if matches else ""
    return f"{risk_label} risk based on affected areas: {modules}.{knowledge_text}"


def _confidence(risk: RiskLevel, matches: tuple[KnowledgeEntry, ...]) -> float:
    if _is_high(risk):
        base = 0.72
    elif risk is RiskLevel.MEDIUM:
        base = 0.76
    else:
        base = 0.82
    if matches:
        base += 0.02
    return min(base, 0.9)


def _terms_from_title_and_impact(title: str, impact: BehaviourImpact) -> tuple[str, ...]:
    words = [word.strip(".,:;()[]{}#").lower() for word in title.split()]
    modules = [area.module.lower() for area in impact.areas]
    file_terms = [part.lower() for area in impact.areas for file in area.affected_files for part in file.replace(".", "/").split("/")]
    return tuple(dict.fromkeys(word for word in (*words, *modules, *file_terms) if len(word) >= 3))


def _is_high(risk: RiskLevel) -> bool:
    return risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
