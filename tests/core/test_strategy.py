"""Tests for Step 3 knowledge lookup and strategy planning."""

from __future__ import annotations

from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    CIFeedbackContext,
    CIHistoricalEvidence,
    CIObservation,
    CIReadinessState,
    ImpactArea,
    RiskLevel,
)
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


def test_strategy_includes_current_head_ci_failure_without_mixing_stale_history() -> None:
    impact = BehaviourImpact(
        summary="Changed payment API",
        areas=(
            ImpactArea(
                module="src/api",
                description="modified src/api/payments.py",
                risk_level=RiskLevel.MEDIUM,
                affected_files=("src/api/payments.py",),
            ),
        ),
        overall_risk=RiskLevel.MEDIUM,
    )
    ci_feedback = CIFeedbackContext(
        current_head_sha="sha-current",
        readiness=CIReadinessState.CHECKS_FAILED,
        current_observations=(
            CIObservation(
                workflow_name="Tests",
                conclusion="failure",
                run_url="https://github.com/acme/web/actions/runs/1",
                failed_jobs=("pytest", "mypy"),
                commit_sha="sha-current",
            ),
        ),
        historical_evidence=(
            CIHistoricalEvidence(
                head_sha="sha-old",
                observations=(
                    CIObservation(
                        workflow_name="Tests",
                        conclusion="failure",
                        run_url="https://github.com/acme/web/actions/runs/0",
                        failed_jobs=("pytest",),
                        commit_sha="sha-old",
                    ),
                ),
            ),
        ),
    )

    result = RuleBasedPRStrategyEngine().plan(
        repo_full_name="acme-corp/web-api",
        pr_number=123,
        title="feat: update payment API",
        impact=impact,
        ci_feedback=ci_feedback,
    )

    ci_actions = [action for action in result.actions if action.target.startswith("ci:")]
    assert [(action.action_type, action.target, action.priority) for action in ci_actions] == [
        (ActionType.RUN_TESTS, "ci:Tests", 4),
        (ActionType.RUN_TESTS, "ci:Tests/pytest", 5),
        (ActionType.TYPE_CHECK, "ci:Tests/mypy", 5),
    ]
    assert "current-head CI/check feedback: Tests=failure" in result.reasoning
    assert "failed jobs: pytest, mypy" in result.reasoning
    assert "historical CI evidence on superseded heads: sha-old: Tests=failure" in result.reasoning
    assert "source of truth: sha-current" in result.reasoning


def test_strategy_represents_success_cancelled_timed_out_and_pending_ci_feedback() -> None:
    impact = BehaviourImpact(summary="Changed runtime worker", areas=(), overall_risk=RiskLevel.LOW)
    ci_feedback = CIFeedbackContext(
        current_head_sha="sha-current",
        readiness=CIReadinessState.WAITING_FOR_CHECKS,
        current_observations=(
            CIObservation(
                workflow_name="Tests",
                conclusion="success",
                run_url="https://github.com/acme/web/actions/runs/2",
                commit_sha="sha-current",
            ),
            CIObservation(
                workflow_name="Deploy",
                conclusion="cancelled",
                run_url="https://github.com/acme/web/actions/runs/3",
                commit_sha="sha-current",
            ),
            CIObservation(
                workflow_name="E2E",
                conclusion="timed_out",
                run_url="https://github.com/acme/web/actions/runs/4",
                failed_jobs=("browser",),
                commit_sha="sha-current",
            ),
        ),
        pending_checks=("Security",),
    )

    result = RuleBasedPRStrategyEngine().plan(
        repo_full_name="acme-corp/web-api",
        pr_number=124,
        title="feat: update worker",
        impact=impact,
        ci_feedback=ci_feedback,
    )

    assert "Tests=success" in result.reasoning
    assert "Deploy=cancelled" in result.reasoning
    assert "E2E=timed_out" in result.reasoning
    assert "pending checks: Security" in result.reasoning
    assert any(action.target == "ci:E2E/browser" and action.priority == 5 for action in result.actions)
    assert any(action.target == "ci:Deploy" and action.priority == 3 for action in result.actions)
