"""Tests for Step 3 PR workflow context acquisition."""

from __future__ import annotations

from datetime import UTC, datetime

from src.adapters.connectors.github import FileDiff, PRMeta
from src.core.analyzer import PRAnalysisContext
from src.core.contracts import EventMeta, EventSource, EventType, FileChange, PREvent, PROpened, RiskLevel
from src.runtime.orchestrator import PRWorkflowOrchestrator


class RecordingGitHubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta:
        self.calls.append(("pr", owner, number))
        return PRMeta(
            number=number,
            title="feat: fetched title",
            state="open",
            head_sha="abc123",
            base_ref="main",
            head_ref="feat/fetched",
            author="Kimcheolhui",
            draft=False,
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}",
        )

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]:
        self.calls.append(("files", owner, number))
        return [
            FileDiff(
                filename="src/api/refunds.py",
                status="added",
                additions=25,
                deletions=0,
                changes=25,
                patch="@@\n+@router.post('/refunds')\n+def refund(): ...\n",
            )
        ]

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        self.calls.append(("diff", owner, number))
        return "diff --git a/src/api/refunds.py b/src/api/refunds.py"


def _event() -> PROpened:
    return PROpened(
        meta=EventMeta(
            event_id="evt-step3",
            event_type=EventType.PR_OPENED,
            correlation_id="corr-step3",
            timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=UTC),
            source=EventSource.GITHUB,
        ),
        repo_full_name="acme-corp/web-api",
        pr_number=123,
        title="feat: webhook title",
        body="Webhook body",
        author="octocat",
        base_branch="main",
        head_branch="feat/webhook",
        diff_url="https://github.com/acme-corp/web-api/pull/123.diff",
        files_changed=(FileChange(path="placeholder.txt", status="modified"),),
    )


def test_pr_workflow_uses_context_provider_instead_of_webhook_file_placeholders() -> None:
    class StaticContextProvider:
        def load(self, event: PREvent) -> PRAnalysisContext:
            return PRAnalysisContext(
                repo_full_name=event.repo_full_name,
                pr_number=event.pr_number,
                title="feat: fetched refund api",
                body=event.body,
                base_branch=event.base_branch,
                head_branch=event.head_branch,
                files=(
                    # If the workflow uses webhook placeholders, this API area will be missing.
                    PRAnalysisContext.file(
                        path="src/api/refunds.py",
                        status="added",
                        additions=25,
                        deletions=0,
                        patch="@@\n+@router.post('/refunds')\n+def refund(): ...\n",
                    ),
                ),
                unified_diff="diff --git a/src/api/refunds.py b/src/api/refunds.py",
            )

    result = PRWorkflowOrchestrator(context_provider=StaticContextProvider()).run(_event())

    assert result.impact.overall_risk is RiskLevel.LOW
    assert result.impact.areas[0].module == "src/api"
    assert "placeholder.txt" not in result.report.summary_markdown
    assert "Behaviour Impact Report" in result.comment_payload.body
