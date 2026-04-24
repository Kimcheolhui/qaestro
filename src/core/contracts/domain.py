"""Domain types for qaestro's core analysis pipeline.

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


@unique
class ActionType(Enum):
    """Known validation-action categories emitted by the Strategy Engine.

    The ``CUSTOM`` member is an intentional escape hatch: the engine is
    LLM-driven and may legitimately propose action shapes we have not
    enumerated yet.  When :attr:`StrategyAction.action_type` is
    :attr:`CUSTOM`, consumers should fall back to :attr:`StrategyAction.description`
    for human-readable intent and to :attr:`StrategyAction.target` for the
    concrete object the action operates on.

    Prefer adding a new enum member over emitting ``CUSTOM`` when a category
    starts showing up consistently.
    """

    RUN_TESTS = "run_tests"
    RUN_LINTER = "run_linter"
    TYPE_CHECK = "type_check"
    CHECK_SECURITY = "check_security"
    VERIFY_API_CONTRACT = "verify_api_contract"
    SMOKE_TEST = "smoke_test"
    CUSTOM = "custom"  # escape hatch — see class docstring


@dataclass(frozen=True)
class ImpactArea:
    """An area of the analysed project that is touched by a change.

    ``module`` refers to a logical module of the **target project being
    analysed** (e.g. ``"auth"``, ``"payments"``, ``"api.v2"``) — not to
    qaestro's own internal modules.  The Behaviour Analyzer is responsible
    for mapping changed file paths to module names; when the target
    project lacks a stable module taxonomy (or renames modules), the
    Analyzer should fall back to directory-prefix names or file paths.
    """

    module: str
    description: str
    risk_level: RiskLevel
    affected_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class BehaviourImpact:
    """Output of the Behaviour Analyzer.

    ``raw_diff_stats`` is an open-ended dict so the Analyzer can attach
    whatever numeric stats it finds useful without a schema change.
    Typical keys: ``"additions"``, ``"deletions"``, ``"files_changed"``,
    ``"files_added"``, ``"files_modified"``, ``"files_removed"``.
    """

    summary: str
    areas: tuple[ImpactArea, ...]
    overall_risk: RiskLevel
    raw_diff_stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyAction:
    """A single validation action recommended by the Strategy Engine.

    Field conventions:

    * ``action_type`` — the category of the action.  See :class:`ActionType`
      for the known enum values plus the ``CUSTOM`` escape hatch.
    * ``target`` — the concrete object the action operates on.  Its
      format depends on ``action_type``:

        ======================  ===============================================
        action_type             target format
        ======================  ===============================================
        RUN_TESTS               test file path or directory (e.g. ``tests/``)
        RUN_LINTER              source directory (e.g. ``src/``)
        TYPE_CHECK              source directory or package name
        CHECK_SECURITY          ``path:line`` or a source file
        VERIFY_API_CONTRACT     HTTP method + route (e.g. ``POST /api/login``)
        SMOKE_TEST              endpoint URL or scenario id
        CUSTOM                  free-form — see ``description``
        ======================  ===============================================

    * ``priority`` — **higher integer = more urgent.**  Recommended scale:
      ``0`` (default/normal), ``1-2`` (elevated), ``3`` (high),
      ``4+`` (critical / must-run).  There is no hard upper bound; consumers
      should sort by this field descending.
    * ``rationale`` — natural-language reason the engine picked this action.
      Crucial for auditability of LLM decisions; may be empty for
      deterministic rules.
    """

    action_type: ActionType
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
