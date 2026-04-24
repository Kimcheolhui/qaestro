"""Shared event types and domain models.

This package re-exports every public type so consumers can write::

    from src.core.contracts import PROpened, RiskLevel, QAReport
"""

from __future__ import annotations

from .domain import (
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
from .events import (
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
from .parsers import (
    parse_github_ci_event,
    parse_github_comment_event,
    parse_github_pr_event,
    parse_github_pr_review_event,
)

__all__ = [
    "ActionType",
    "BehaviourImpact",
    "CICompleted",
    "ChatMention",
    "Event",
    "EventMeta",
    "EventSource",
    "EventType",
    "FileChange",
    "ImpactArea",
    "PRCommented",
    "PREvent",
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
