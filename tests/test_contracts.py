"""Unit tests for core contract types — events and domain models.

Verifies immutability (frozen), enum correctness, default values,
and the Event union type alias.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from src.core.contracts.domain import (
    ActionType,
    BehaviourImpact,
    ImpactArea,
    QAReport,
    RiskLevel,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)
from src.core.contracts.events import (
    ChatMention,
    CICompleted,
    Event,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    PRCommented,
    PREvent,
    PROpened,
    PRReviewed,
    PRUpdated,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(event_type: EventType = EventType.PR_OPENED) -> EventMeta:
    return EventMeta(
        event_id="evt-001",
        event_type=event_type,
        correlation_id="corr-001",
        timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------


class TestEventTypeEnum:
    """EventType enum values and membership."""

    def test_values(self):
        assert EventType.PR_OPENED.value == "pr_opened"
        assert EventType.PR_UPDATED.value == "pr_updated"
        assert EventType.PR_COMMENTED.value == "pr_commented"
        assert EventType.PR_REVIEWED.value == "pr_reviewed"
        assert EventType.CI_COMPLETED.value == "ci_completed"
        assert EventType.CHAT_MENTION.value == "chat_mention"

    def test_member_count(self):
        assert len(EventType) == 6

    def test_unique_values(self):
        values = [e.value for e in EventType]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# EventSource enum
# ---------------------------------------------------------------------------


class TestEventSourceEnum:
    """EventSource enum — constrained source origins."""

    def test_values(self):
        assert EventSource.GITHUB.value == "github"
        assert EventSource.SLACK.value == "slack"
        assert EventSource.TEAMS.value == "teams"
        assert EventSource.REPLAY.value == "replay"

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError):
            EventSource("gitlab")


# ---------------------------------------------------------------------------
# EventMeta
# ---------------------------------------------------------------------------


class TestEventMeta:
    """EventMeta is frozen and carries correct fields."""

    def test_fields(self):
        meta = _make_meta()
        assert meta.event_id == "evt-001"
        assert meta.event_type == EventType.PR_OPENED
        assert meta.correlation_id == "corr-001"
        assert meta.source == EventSource.GITHUB

    def test_frozen(self):
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.event_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FileChange
# ---------------------------------------------------------------------------


class TestFileChange:
    """FileChange defaults and immutability."""

    def test_defaults(self):
        fc = FileChange(path="src/main.py", status="modified")
        assert fc.additions == 0
        assert fc.deletions == 0
        assert fc.previous_filename == ""

    def test_renamed_carries_previous_filename(self):
        fc = FileChange(
            path="src/new_name.py",
            status="renamed",
            previous_filename="src/old_name.py",
        )
        assert fc.previous_filename == "src/old_name.py"

    def test_no_patch_field(self):
        """Ensure FileChange stays lightweight — patch text is not carried."""
        fields = {f.name for f in dataclasses.fields(FileChange)}
        assert "patch" not in fields

    def test_frozen(self):
        fc = FileChange(path="a.py", status="added")
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.path = "b.py"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PR events
# ---------------------------------------------------------------------------


class TestPREventInheritance:
    """PROpened and PRUpdated share the PREvent base."""

    def test_pr_opened_is_pr_event(self):
        pr = PROpened(
            meta=_make_meta(),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        assert isinstance(pr, PREvent)

    def test_pr_updated_is_pr_event(self):
        pr = PRUpdated(
            meta=_make_meta(EventType.PR_UPDATED),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        assert isinstance(pr, PREvent)

    def test_distinct_types(self):
        po = PROpened(
            meta=_make_meta(),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        assert not isinstance(po, PRUpdated)


class TestPROpened:
    """PROpened construction and immutability."""

    def test_construction(self):
        fc = FileChange(path="x.py", status="added", additions=10)
        pr = PROpened(
            meta=_make_meta(EventType.PR_OPENED),
            repo_full_name="acme-corp/web-api",
            pr_number=42,
            title="feat: stuff",
            body="Does things",
            author="alice",
            base_branch="main",
            head_branch="feat/stuff",
            diff_url="https://example.com/diff",
            files_changed=(fc,),
        )
        assert pr.pr_number == 42
        assert len(pr.files_changed) == 1
        assert pr.files_changed[0].path == "x.py"

    def test_default_files_changed(self):
        pr = PROpened(
            meta=_make_meta(),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="b",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        assert pr.files_changed == ()

    def test_frozen(self):
        pr = PROpened(
            meta=_make_meta(),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="b",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            pr.pr_number = 999  # type: ignore[misc]


class TestPRUpdated:
    """PRUpdated mirrors PROpened structure."""

    def test_construction(self):
        pr = PRUpdated(
            meta=_make_meta(EventType.PR_UPDATED),
            repo_full_name="o/r",
            pr_number=7,
            title="fix: bug",
            body="",
            author="bob",
            base_branch="main",
            head_branch="fix/bug",
            diff_url="",
        )
        assert pr.meta.event_type == EventType.PR_UPDATED


class TestPRCommented:
    """PRCommented defaults and construction."""

    def test_defaults(self):
        c = PRCommented(
            meta=_make_meta(EventType.PR_COMMENTED),
            repo_full_name="o/r",
            pr_number=1,
            comment_id=555,
            author="charlie",
            body="Looks good",
        )
        assert c.is_review_comment is False
        assert c.path == ""
        assert c.line is None


class TestPRReviewed:
    """PRReviewed construction."""

    def test_construction(self):
        r = PRReviewed(
            meta=_make_meta(EventType.PR_REVIEWED),
            repo_full_name="o/r",
            pr_number=1,
            reviewer="dana",
            state="approved",
        )
        assert r.body == ""
        assert r.state == "approved"


# ---------------------------------------------------------------------------
# CI event
# ---------------------------------------------------------------------------


class TestCICompleted:
    """CICompleted defaults and construction."""

    def test_success(self):
        ci = CICompleted(
            meta=_make_meta(EventType.CI_COMPLETED),
            repo_full_name="o/r",
            pr_number=42,
            commit_sha="abc123",
            workflow_name="CI",
            conclusion="success",
            run_url="https://example.com/run/1",
        )
        assert ci.failed_jobs == ()
        assert ci.logs_url == ""

    def test_failure(self):
        ci = CICompleted(
            meta=_make_meta(EventType.CI_COMPLETED),
            repo_full_name="o/r",
            pr_number=None,
            commit_sha="def456",
            workflow_name="CI",
            conclusion="failure",
            run_url="https://example.com/run/2",
            failed_jobs=("build", "test"),
        )
        assert ci.pr_number is None
        assert len(ci.failed_jobs) == 2

    def test_frozen(self):
        ci = CICompleted(
            meta=_make_meta(EventType.CI_COMPLETED),
            repo_full_name="o/r",
            pr_number=1,
            commit_sha="x",
            workflow_name="CI",
            conclusion="success",
            run_url="",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ci.conclusion = "failure"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Chat event
# ---------------------------------------------------------------------------


class TestChatMention:
    """ChatMention defaults."""

    def test_defaults(self):
        cm = ChatMention(
            meta=_make_meta(EventType.CHAT_MENTION),
            platform="slack",
            channel_id="C123",
            channel_name="engineering",
            author="eve",
            message="@qaestro check PR 42",
        )
        assert cm.thread_id == ""
        assert cm.referenced_pr is None


# ---------------------------------------------------------------------------
# Event union type alias
# ---------------------------------------------------------------------------


class TestEventUnion:
    """The Event type alias covers all concrete event types."""

    def test_pr_opened_is_event(self):
        pr = PROpened(
            meta=_make_meta(),
            repo_full_name="o/r",
            pr_number=1,
            title="t",
            body="",
            author="a",
            base_branch="main",
            head_branch="dev",
            diff_url="",
        )
        # This is a structural check — the union type is just a type alias,
        # so we verify each concrete type is in the union's __args__
        event_types = Event.__args__ if hasattr(Event, "__args__") else []
        assert PROpened in event_types
        assert PRUpdated in event_types
        assert PRCommented in event_types
        assert PRReviewed in event_types
        assert CICompleted in event_types
        assert ChatMention in event_types
        assert isinstance(pr, PROpened)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class TestRiskLevel:
    """RiskLevel enum."""

    def test_values(self):
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_member_count(self):
        assert len(RiskLevel) == 4


class TestActionType:
    """ActionType enum — known categories plus CUSTOM escape hatch."""

    def test_known_values(self):
        assert ActionType.RUN_TESTS.value == "run_tests"
        assert ActionType.RUN_LINTER.value == "run_linter"
        assert ActionType.TYPE_CHECK.value == "type_check"
        assert ActionType.CHECK_SECURITY.value == "check_security"
        assert ActionType.VERIFY_API_CONTRACT.value == "verify_api_contract"
        assert ActionType.SMOKE_TEST.value == "smoke_test"

    def test_custom_escape_hatch(self):
        assert ActionType.CUSTOM.value == "custom"

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError):
            ActionType("not_a_real_action")


class TestValidationOutcome:
    """ValidationOutcome enum."""

    def test_values(self):
        assert ValidationOutcome.PASS.value == "pass"
        assert ValidationOutcome.FAIL.value == "fail"
        assert ValidationOutcome.ERROR.value == "error"
        assert ValidationOutcome.SKIPPED.value == "skipped"


class TestImpactArea:
    """ImpactArea construction and defaults."""

    def test_defaults(self):
        ia = ImpactArea(module="auth", description="Authentication module", risk_level=RiskLevel.HIGH)
        assert ia.affected_files == ()

    def test_frozen(self):
        ia = ImpactArea(module="auth", description="d", risk_level=RiskLevel.LOW)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ia.module = "payments"  # type: ignore[misc]


class TestBehaviourImpact:
    """BehaviourImpact — default dict factory."""

    def test_default_stats(self):
        bi = BehaviourImpact(summary="s", areas=(), overall_risk=RiskLevel.LOW)
        assert bi.raw_diff_stats == {}

    def test_with_stats(self):
        bi = BehaviourImpact(
            summary="s",
            areas=(),
            overall_risk=RiskLevel.MEDIUM,
            raw_diff_stats={"additions": 42, "deletions": 10},
        )
        assert bi.raw_diff_stats["additions"] == 42


class TestStrategyAction:
    """StrategyAction defaults and ActionType usage."""

    def test_defaults(self):
        sa = StrategyAction(action_type=ActionType.RUN_TESTS, description="Run unit tests", target="tests/")
        assert sa.priority == 0
        assert sa.rationale == ""
        assert sa.action_type is ActionType.RUN_TESTS

    def test_custom_action(self):
        """CUSTOM is a valid escape hatch for engine-proposed novel actions."""
        sa = StrategyAction(
            action_type=ActionType.CUSTOM,
            description="Run a custom migration-safety probe",
            target="scripts/check_migration.py",
            rationale="DB schema change detected; no standard action fits",
        )
        assert sa.action_type is ActionType.CUSTOM


class TestStrategyResult:
    """StrategyResult defaults."""

    def test_defaults(self):
        sr = StrategyResult(actions=(), reasoning="No changes detected", confidence=1.0)
        assert sr.knowledge_refs == ()


class TestValidationResult:
    """ValidationResult defaults."""

    def test_defaults(self):
        action = StrategyAction(action_type=ActionType.RUN_TESTS, description="d", target="t")
        vr = ValidationResult(action=action, outcome=ValidationOutcome.PASS)
        assert vr.details == ""
        assert vr.duration_seconds == 0.0
        assert vr.artifacts == ()


class TestQAReport:
    """QAReport full construction."""

    def test_full_report(self):
        area = ImpactArea(module="auth", description="Auth changes", risk_level=RiskLevel.HIGH)
        impact = BehaviourImpact(summary="Auth middleware added", areas=(area,), overall_risk=RiskLevel.HIGH)
        action = StrategyAction(
            action_type=ActionType.RUN_TESTS,
            description="Run auth tests",
            target="tests/test_auth.py",
        )
        strategy = StrategyResult(actions=(action,), reasoning="New auth code needs testing", confidence=0.9)
        validation = ValidationResult(action=action, outcome=ValidationOutcome.PASS, duration_seconds=1.5)
        report = QAReport(
            event_id="evt-001",
            repo_full_name="acme-corp/web-api",
            pr_number=123,
            impact=impact,
            strategy=strategy,
            validations=(validation,),
            summary_markdown="## QA Report\n\nAll checks passed.",
        )
        assert report.pr_number == 123
        assert len(report.validations) == 1
        assert report.validations[0].outcome == ValidationOutcome.PASS
