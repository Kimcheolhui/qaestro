"""Tests for the Step 3 Behaviour Analyzer implementation."""

from __future__ import annotations

from src.core.analyzer import PRAnalysisContext, PRFileDiff, PRFileStatus, RuleBasedPRBehaviourAnalyzer
from src.core.contracts import RiskLevel


def test_pr_file_diff_normalizes_status_and_documents_path_semantics() -> None:
    file = PRAnalysisContext.file(
        path="src/new_name.py",
        status="renamed",
        additions=3,
        deletions=1,
        previous_filename="src/old_name.py",
    )

    assert file.path == "src/new_name.py"
    assert file.previous_filename == "src/old_name.py"
    assert file.status is PRFileStatus.RENAMED


def test_analyzer_groups_files_by_observed_path_groups_and_aggregates_risk() -> None:
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
                status=PRFileStatus.MODIFIED,
                additions=40,
                deletions=12,
                patch="@@\n+@router.post('/refunds')\n+def refund():\n+    return service.refund()\n",
            ),
            PRFileDiff(
                path="tests/api/test_payments.py",
                status=PRFileStatus.MODIFIED,
                additions=30,
                deletions=0,
                patch="@@\n+def test_refund(): ...\n",
            ),
            PRFileDiff(
                path="README.md",
                status=PRFileStatus.MODIFIED,
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
        "files_copied": 0,
        "files_unchanged": 0,
        "files_unknown": 0,
    }
    assert "src/api/payments.py" in impact.summary
    assert "3 files" in impact.summary
    assert [(area.module, area.risk_level) for area in impact.areas] == [
        ("README.md", RiskLevel.LOW),
        ("src/api", RiskLevel.MEDIUM),
        ("tests/api", RiskLevel.LOW),
    ]


def test_analyzer_counts_every_normalized_file_status_in_diff_stats() -> None:
    context = PRAnalysisContext(
        repo_full_name="acme-corp/web-api",
        pr_number=126,
        title="chore: exercise status counters",
        body="Synthetic status coverage.",
        base_branch="main",
        head_branch="chore/statuses",
        files=(
            PRFileDiff(path="src/created.py", status=PRFileStatus.ADDED, additions=3),
            PRFileDiff(path="src/modified.py", status=PRFileStatus.MODIFIED, additions=4, deletions=1),
            PRFileDiff(path="src/changed.py", status=PRFileStatus.CHANGED, additions=2, deletions=2),
            PRFileDiff(path="src/deleted.py", status=PRFileStatus.REMOVED, deletions=5),
            PRFileDiff(path="src/new_name.py", status=PRFileStatus.RENAMED, previous_filename="src/old_name.py"),
            PRFileDiff(path="src/copied.py", status=PRFileStatus.COPIED, additions=1),
            PRFileDiff(path="src/same.py", status=PRFileStatus.UNCHANGED),
            PRFileDiff(path="src/provider-specific.py", status=PRFileStatus.UNKNOWN),
        ),
    )

    impact = RuleBasedPRBehaviourAnalyzer().analyze(context)

    assert impact.raw_diff_stats == {
        "files_changed": 8,
        "additions": 10,
        "deletions": 8,
        "files_added": 1,
        "files_modified": 2,
        "files_removed": 1,
        "files_renamed": 1,
        "files_copied": 1,
        "files_unchanged": 1,
        "files_unknown": 1,
    }


def test_analyzer_uses_actual_repo_path_groups_instead_of_fixed_module_labels() -> None:
    context = PRAnalysisContext(
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=125,
        title="feat: update runtime wiring",
        body="Changes orchestration internals.",
        base_branch="main",
        head_branch="feat/runtime",
        files=(
            PRFileDiff(
                path="src/adapters/connectors/github/client.py",
                status=PRFileStatus.MODIFIED,
                additions=80,
                deletions=20,
            ),
            PRFileDiff(
                path="src/runtime/orchestrator/pr_workflow.py",
                status=PRFileStatus.MODIFIED,
                additions=25,
                deletions=5,
            ),
        ),
    )

    impact = RuleBasedPRBehaviourAnalyzer().analyze(context)

    assert [(area.module, area.risk_level, area.affected_files) for area in impact.areas] == [
        (
            "src/adapters/connectors/github",
            RiskLevel.MEDIUM,
            ("src/adapters/connectors/github/client.py",),
        ),
        (
            "src/runtime/orchestrator",
            RiskLevel.LOW,
            ("src/runtime/orchestrator/pr_workflow.py",),
        ),
    ]


def test_analyzer_escalates_high_risk_from_diff_signals_and_change_size_not_module_names() -> None:
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
                status=PRFileStatus.MODIFIED,
                additions=80,
                deletions=20,
                patch="@@\n+permissions:\n+  contents: read\n+  deployments: write\n",
            ),
            PRFileDiff(
                path="infra/terraform/main.tf",
                status=PRFileStatus.MODIFIED,
                additions=180,
                deletions=40,
                patch='@@\n+resource "azurerm_linux_web_app" "app" {}\n',
            ),
            PRFileDiff(
                path="config/production.yml",
                status=PRFileStatus.MODIFIED,
                additions=35,
                deletions=10,
                patch="@@\n+feature_flags:\n+  refunds: true\n",
            ),
        ),
        unified_diff="diff --git a/infra/terraform/main.tf b/infra/terraform/main.tf",
    )

    impact = RuleBasedPRBehaviourAnalyzer().analyze(context)

    assert impact.overall_risk is RiskLevel.HIGH
    risks_by_group = {area.module: area.risk_level for area in impact.areas}
    assert risks_by_group[".github/workflows"] is RiskLevel.HIGH
    assert risks_by_group["infra/terraform"] is RiskLevel.HIGH
    assert risks_by_group["config"] is RiskLevel.MEDIUM
