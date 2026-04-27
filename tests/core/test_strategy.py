"""Tests for Step 3 knowledge lookup and strategy planning."""

from __future__ import annotations

from src.core.contracts import ActionType, BehaviourImpact, ImpactArea, RiskLevel
from src.core.knowledge import InMemoryKnowledgeBase, KnowledgeEntry, KnowledgeQuery
from src.core.strategy import RuleBasedPRStrategyEngine


def test_in_memory_knowledge_base_matches_repo_and_query_text_deterministically() -> None:
    knowledge = InMemoryKnowledgeBase(
        entries=(
            KnowledgeEntry(
                key="payments-refund-contract",
                summary="Payment refund API changes require refund contract checks.",
                repos=("acme-corp/web-api",),
                checklist_items=("Verify POST /refunds contract",),
            ),
            KnowledgeEntry(
                key="other-repo-ui",
                summary="Refund UI rule for a different repository.",
                repos=("other/repo",),
                checklist_items=("Check UI manually",),
            ),
        )
    )

    matches = knowledge.search(
        KnowledgeQuery(
            repo_full_name="acme-corp/web-api",
            query_text="refund contract",
        )
    )

    assert tuple(entry.key for entry in matches) == ("payments-refund-contract",)


def test_strategy_generates_deterministic_actions_from_risk_areas_and_knowledge() -> None:
    impact = BehaviourImpact(
        summary="Changed payment API and checkout UI",
        areas=(
            ImpactArea(
                module="src/api",
                description="modified src/api/payments.py",
                risk_level=RiskLevel.MEDIUM,
                affected_files=("src/api/payments.py",),
            ),
            ImpactArea(
                module="src/web/checkout",
                description="modified src/web/checkout/RefundForm.tsx",
                risk_level=RiskLevel.MEDIUM,
                affected_files=("src/web/checkout/RefundForm.tsx",),
            ),
        ),
        overall_risk=RiskLevel.MEDIUM,
        raw_diff_stats={"files_changed": 2, "additions": 50, "deletions": 10},
    )
    knowledge = InMemoryKnowledgeBase(
        entries=(
            KnowledgeEntry(
                key="refund-regression",
                summary="Refund changes previously broke zero-amount edge cases.",
                repos=("acme-corp/web-api",),
                checklist_items=("Exercise zero-amount refund edge case",),
            ),
        )
    )

    result = RuleBasedPRStrategyEngine(knowledge=knowledge).plan(
        repo_full_name="acme-corp/web-api",
        pr_number=123,
        title="feat: add refund flow",
        impact=impact,
    )

    assert result.confidence == 0.78
    assert result.knowledge_refs == ("refund-regression",)
    assert result.reasoning.startswith("Medium risk")
    assert [(action.action_type, action.target) for action in result.actions] == [
        (ActionType.RUN_TESTS, "tests/src/api"),
        (ActionType.RUN_TESTS, "tests/src/web/checkout"),
        (ActionType.RUN_TESTS, "tests/"),
        (ActionType.CUSTOM, "knowledge:refund-regression"),
    ]
    assert [action.priority for action in result.actions] == [2, 2, 2, 4]
    assert "zero-amount" in result.actions[-1].description


def test_strategy_generates_generic_actions_for_repo_observed_groups() -> None:
    impact = BehaviourImpact(
        summary="Changed adapter module",
        areas=(
            ImpactArea(
                module="src/adapters/connectors/github",
                description="modified src/adapters/connectors/github/client.py",
                risk_level=RiskLevel.LOW,
                affected_files=("src/adapters/connectors/github/client.py",),
            ),
        ),
        overall_risk=RiskLevel.LOW,
    )

    result = RuleBasedPRStrategyEngine().plan(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=39,
        title="feat: update connector",
        impact=impact,
    )

    assert result.actions
    assert result.actions[0].action_type is ActionType.RUN_TESTS
    assert result.actions[0].target == "tests/src/adapters/connectors/github"
    assert result.actions[1].target == "tests/"


def test_strategy_skips_low_signal_doc_groups_for_step3_test_actions() -> None:
    impact = BehaviourImpact(
        summary="Changed documentation only",
        areas=(
            ImpactArea(
                module="docs",
                description="modified docs/ARCHITECTURE.md",
                risk_level=RiskLevel.LOW,
                affected_files=("docs/ARCHITECTURE.md",),
            ),
            ImpactArea(
                module="CHANGELOG.md",
                description="modified CHANGELOG.md",
                risk_level=RiskLevel.LOW,
                affected_files=("CHANGELOG.md",),
            ),
        ),
        overall_risk=RiskLevel.LOW,
    )

    result = RuleBasedPRStrategyEngine().plan(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=40,
        title="docs: update architecture notes",
        impact=impact,
    )

    assert result.actions == ()
