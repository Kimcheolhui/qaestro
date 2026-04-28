"""Closed workflow stage names shared across runtime orchestration."""

from __future__ import annotations

from enum import StrEnum


class WorkflowStage(StrEnum):
    """Canonical stage names for qaestro's structured PR workflow."""

    CONTEXT = "context"
    TRIAGE = "triage"
    ANALYZER = "analyzer"
    STRATEGY = "strategy"
    VALIDATOR = "validator"
    RENDERER = "renderer"
    OUTPUT = "output"
