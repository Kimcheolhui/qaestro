"""Tests for the Step 3 Behaviour Analyzer implementation."""

from __future__ import annotations

from src.core.analyzer import PRAnalysisContext, PRFileDiff, RuleBasedPRBehaviourAnalyzer
from src.core.contracts import RiskLevel


def test_analyzer_classifies_impact_areas_and_aggregates_medium_risk() -> None:
    context = PRAnalysisContext(
        repo_full_name="acme-corp/web-api",
        pr_number=123,
        title="feat: update payment api",
        body="Adds a refund endpoint.",
        base_branch="main",
        head_branch="feat/refund",
        files=(
            PRFileDiff(
                path="src/api/payments.py",
                status="modified",
                additions=40,
                deletions=12,
                patch="@@\n+@router.post('/refunds')\n+def refund():\n+    return service.refund()\n",
            ),
            PRFileDiff(
                path="tests/api/test_payments.py",
                status="modified",
                additions=30,
                deletions=0,
                patch="@@\n+def test_refund(): ...\n",
            ),
            PRFileDiff(
                path="README.md",
                status="modified",
                additions=5,
                deletions=1,
                patch="@@\n+Refund endpoint documented\n",
            ),
        ),
        unified_diff="diff --git a/src/api/payments.py b/src/api/payments.py",
    )

    impact = RuleBasedPRBehaviourAnalyzer().analyze(context)

    assert impact.overall_risk is RiskLevel.MEDIUM
    assert impact.raw_diff_stats == {
        "files_changed": 3,
        "additions": 75,
        "deletions": 13,
        "files_added": 0,
        "files_modified": 3,
        "files_removed": 0,
        "files_renamed": 0,
    }
    assert "src/api/payments.py" in impact.summary
    assert "3 files" in impact.summary
    assert [(area.module, area.risk_level) for area in impact.areas] == [
        ("api", RiskLevel.MEDIUM),
        ("tests", RiskLevel.LOW),
        ("docs", RiskLevel.LOW),
    ]


def test_analyzer_escalates_high_risk_for_large_infra_and_config_changes() -> None:
    context = PRAnalysisContext(
        repo_full_name="acme-corp/web-api",
        pr_number=124,
        title="refactor: deploy pipeline",
        body="Changes deployment settings.",
        base_branch="main",
        head_branch="infra/deploy",
        files=(
            PRFileDiff(
                path=".github/workflows/deploy.yml",
                status="modified",
                additions=80,
                deletions=20,
                patch="@@\n+permissions:\n+  contents: read\n+  deployments: write\n",
            ),
            PRFileDiff(
                path="infra/terraform/main.tf",
                status="modified",
                additions=180,
                deletions=40,
                patch="@@\n+resource \"azurerm_linux_web_app\" \"app\" {}\n",
            ),
            PRFileDiff(
                path="config/production.yml",
                status="modified",
                additions=35,
                deletions=10,
                patch="@@\n+feature_flags:\n+  refunds: true\n",
            ),
        ),
        unified_diff="diff --git a/infra/terraform/main.tf b/infra/terraform/main.tf",
    )

    impact = RuleBasedPRBehaviourAnalyzer().analyze(context)

    assert impact.overall_risk is RiskLevel.HIGH
    assert {area.module for area in impact.areas} == {"infra", "config"}
    assert all(area.risk_level is RiskLevel.HIGH for area in impact.areas)
    assert "infra" in impact.summary
