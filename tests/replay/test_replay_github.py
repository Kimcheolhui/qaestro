"""Replay tests that load GitHub webhook fixture files and run them through the parsers.

Each test loads a JSON fixture, feeds it through the appropriate parser,
and asserts the resulting event object has the expected shape and values.
"""

from __future__ import annotations

import json
import pathlib

from src.core.contracts.events import (
    CICompleted,
    EventSource,
    EventType,
    PRCommented,
    PROpened,
    PRReviewed,
    PRUpdated,
)
from src.core.contracts.parsers import (
    parse_github_ci_event,
    parse_github_comment_event,
    parse_github_pr_event,
    parse_github_pr_review_event,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


class TestGitHubPRReplay:
    """Replay GitHub pull_request webhook payloads."""

    def test_pr_opened(self):
        payload = json.loads((FIXTURES / "github_pr_opened.json").read_text())
        event = parse_github_pr_event(payload, action="opened", correlation_id="test-001")
        assert event is not None
        assert isinstance(event, PROpened)
        assert event.meta.event_type == EventType.PR_OPENED
        assert event.meta.source == EventSource.GITHUB
        assert event.meta.correlation_id == "test-001"
        assert event.pr_number == 123
        assert event.repo_full_name == "acme-corp/web-api"
        assert event.author == "jane-dev"
        assert event.base_branch == "main"
        assert event.head_branch == "feat/auth-middleware"
        assert event.head_sha == "def789abc123456"
        assert len(event.files_changed) == 3
        assert event.files_changed[0].path == "src/middleware/auth_middleware.py"
        assert event.files_changed[0].status == "added"

    def test_pr_updated(self):
        payload = json.loads((FIXTURES / "github_pr_synchronize.json").read_text())
        event = parse_github_pr_event(payload, action="synchronize", correlation_id="test-002")
        assert event is not None
        assert isinstance(event, PRUpdated)
        assert event.meta.event_type == EventType.PR_UPDATED
        assert event.pr_number == 123
        assert event.repo_full_name == "acme-corp/web-api"
        assert len(event.files_changed) == 1

    def test_unhandled_action_returns_none(self):
        payload = json.loads((FIXTURES / "github_pr_opened.json").read_text())
        for action in ("labeled", "closed", "assigned", "review_requested", "unlabeled"):
            event = parse_github_pr_event(payload, action=action, correlation_id=f"test-skip-{action}")
            assert event is None, f"action={action!r} should return None"

    def test_empty_payload_does_not_crash(self):
        event = parse_github_pr_event({}, action="opened", correlation_id="test-empty")
        assert event is not None  # parsers are tolerant — returns PROpened with default values
        assert event.pr_number == 0
        assert event.repo_full_name == ""
        assert event.files_changed == ()


class TestGitHubCIReplay:
    """Replay GitHub workflow_run webhook payloads."""

    def test_ci_success(self):
        payload = json.loads((FIXTURES / "github_ci_completed_success.json").read_text())
        event = parse_github_ci_event(payload, correlation_id="test-003")
        assert event is not None
        assert isinstance(event, CICompleted)
        assert event.meta.event_type == EventType.CI_COMPLETED
        assert event.meta.source == EventSource.GITHUB
        assert event.conclusion == "success"
        assert event.pr_number == 123
        assert event.repo_full_name == "acme-corp/web-api"
        assert event.workflow_name == "CI Pipeline"
        assert event.run_id == 5551234567
        assert len(event.failed_jobs) == 0

    def test_ci_failure(self):
        payload = json.loads((FIXTURES / "github_ci_completed_failure.json").read_text())
        event = parse_github_ci_event(payload, correlation_id="test-004")
        assert event is not None
        assert isinstance(event, CICompleted)
        assert event.conclusion == "failure"
        assert len(event.failed_jobs) == 2
        assert "test-integration" in event.failed_jobs
        assert "lint-typecheck" in event.failed_jobs

    def test_in_progress_workflow_returns_none(self):
        """workflow_run without a conclusion (still running) should parse to None."""
        payload = {"workflow_run": {"conclusion": None, "name": "CI"}}
        assert parse_github_ci_event(payload, correlation_id="test-ci-none") is None


class TestGitHubReviewReplay:
    """Replay GitHub pull_request_review webhook payloads."""

    def test_review_approved(self):
        payload = json.loads((FIXTURES / "github_pr_review_approved.json").read_text())
        event = parse_github_pr_review_event(payload, correlation_id="test-005")
        assert event is not None
        assert isinstance(event, PRReviewed)
        assert event.meta.event_type == EventType.PR_REVIEWED
        assert event.meta.source == EventSource.GITHUB
        assert event.reviewer == "senior-reviewer"
        assert event.state == "approved"
        assert event.pr_number == 123
        assert event.repo_full_name == "acme-corp/web-api"
        assert "LGTM" in event.body


class TestGitHubCommentReplay:
    """Replay GitHub issue_comment webhook payloads."""

    def test_comment(self):
        payload = json.loads((FIXTURES / "github_pr_comment.json").read_text())
        event = parse_github_comment_event(payload, correlation_id="test-006")
        assert event is not None
        assert isinstance(event, PRCommented)
        assert event.meta.event_type == EventType.PR_COMMENTED
        assert event.author == "bob-qa"
        assert event.pr_number == 123
        assert event.comment_id == 444555666
        assert "rate limiting" in event.body
        assert event.is_review_comment is False

    def test_empty_comment_returns_none(self):
        assert parse_github_comment_event({}, correlation_id="test-empty") is None

    def test_plain_issue_comment_is_dropped(self):
        """issue_comment webhook fires for plain issues too — those must be filtered out."""
        # Simulate an issue_comment payload where the issue is NOT a PR
        # (no ``issue.pull_request`` object injected by GitHub).
        payload = {
            "action": "created",
            "issue": {
                "number": 77,
                "title": "Bug: login button misaligned",
                # NOTE: no "pull_request" key here — this is a plain issue
            },
            "comment": {
                "id": 999,
                "user": {"login": "random-user"},
                "body": "Still happening on Chrome 120",
            },
            "repository": {"full_name": "acme-corp/web-api"},
        }
        assert parse_github_comment_event(payload, correlation_id="test-issue-only") is None
