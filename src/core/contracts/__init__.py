"""Shared event types and domain models.

This package re-exports every public type so consumers can write::

    from src.core.contracts import PROpened, RiskLevel, QAReport
"""

from __future__ import annotations

from src.core.contracts.domain import (
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
    EventType,
    FileChange,
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

__all__ = [
    "BehaviourImpact",
    "CICompleted",
    "ChatMention",
    "Event",
    "EventMeta",
    "EventType",
    "FileChange",
    "ImpactArea",
    "PRCommented",
    "PROpened",
    "PRReviewed",
    "PRUpdated",
    "QAReport",
    "RiskLevel",
    "StrategyAction",
    "StrategyResult",
    "ValidationOutcome",
    "ValidationResult",
    "parse_github_ci_event",
    "parse_github_comment_event",
    "parse_github_pr_event",
    "parse_github_pr_review_event",
]
