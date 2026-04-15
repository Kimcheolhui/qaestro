"""Domain types for devclaw's core analysis pipeline.

These types represent the outputs of the Behaviour Analyzer, Strategy Engine,
Validator, and the final QA Report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, unique


@unique
class RiskLevel(Enum):
    """Risk classification for a code change."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ImpactArea:
    """An area of the system impacted by a change."""

    module: str
    description: str
    risk_level: RiskLevel
    affected_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class BehaviourImpact:
    """Output of the Behaviour Analyzer."""

    summary: str
    areas: tuple[ImpactArea, ...]
    overall_risk: RiskLevel
    raw_diff_stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyAction:
    """A single validation action recommended by the Strategy Engine."""

    action_type: str
    description: str
    target: str
    priority: int = 0
    rationale: str = ""


@dataclass(frozen=True)
class StrategyResult:
    """Output of the Strategy Engine."""

    actions: tuple[StrategyAction, ...]
    reasoning: str
    confidence: float
    knowledge_refs: tuple[str, ...] = ()


@unique
class ValidationOutcome(Enum):
    """Outcome of a single validation action."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ValidationResult:
    """Result of a single validation action."""

    action: StrategyAction
    outcome: ValidationOutcome
    details: str = ""
    duration_seconds: float = 0.0
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class QAReport:
    """Final output — the full report for a PR/event."""

    event_id: str
    repo_full_name: str
    pr_number: int | None
    impact: BehaviourImpact
    strategy: StrategyResult
    validations: tuple[ValidationResult, ...]
    summary_markdown: str
