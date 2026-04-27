"""Tool runtime value contracts for bounded workflow capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.runtime.stages import WorkflowStage


class ToolCapability(StrEnum):
    """High-level capability class used by stage policy gates."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolCall:
    """One auditable tool execution request emitted by a workflow stage."""

    stage: WorkflowStage
    name: str
    input: Mapping[str, Any]
    correlation_id: str


@dataclass(frozen=True)
class ToolResult:
    """Normalized result returned by a tool handler."""

    call: ToolCall
    ok: bool
    output: object | None = None
    error: str = ""


@dataclass(frozen=True)
class ToolAuditEntry:
    """Small in-memory audit record for deterministic tool execution."""

    stage: WorkflowStage
    name: str
    correlation_id: str
    ok: bool
    error: str = ""


ToolHandler = Callable[[ToolCall], object]


@dataclass(frozen=True)
class ToolDefinition:
    """Registered narrow capability exposed through the runtime boundary."""

    name: str
    capabilities: tuple[ToolCapability, ...]
    handler: ToolHandler
