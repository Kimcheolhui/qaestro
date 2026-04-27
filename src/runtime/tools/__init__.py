"""Tool runtime contracts for bounded workflow capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class ToolPolicyError(RuntimeError):
    """Raised when a workflow stage is not allowed to execute a tool."""


class ToolNotFoundError(RuntimeError):
    """Raised when no registered tool matches a requested tool name."""


class ToolCapability(StrEnum):
    """High-level capability class used by stage policy gates."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolCall:
    """One auditable tool execution request emitted by a workflow stage."""

    stage: str
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

    stage: str
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


class StageToolPolicy:
    """Allowlist of tool names and capability classes per workflow stage."""

    def __init__(
        self,
        allowed_tools_by_stage: Mapping[str, tuple[str, ...]],
        *,
        allow_destructive: bool = False,
    ) -> None:
        self._allowed_tools_by_stage = {stage: frozenset(tools) for stage, tools in allowed_tools_by_stage.items()}
        self._allow_destructive = allow_destructive

    def check(self, call: ToolCall, definition: ToolDefinition) -> None:
        allowed_tools = self._allowed_tools_by_stage.get(call.stage, frozenset())
        if call.name not in allowed_tools:
            raise ToolPolicyError(f"tool {call.name!r} is not allowed during {call.stage!r} stage")
        if ToolCapability.DESTRUCTIVE in definition.capabilities and not self._allow_destructive:
            raise ToolPolicyError(f"destructive tool {call.name!r} is denied by default")


class ToolRuntime(Protocol):
    """Minimal runtime surface used by deterministic workflows and future agents."""

    @property
    def audit_log(self) -> tuple[ToolAuditEntry, ...]: ...

    def execute(self, call: ToolCall) -> ToolResult: ...


class RegisteredToolRuntime:
    """Deterministic runtime that executes registered tools through stage policy."""

    def __init__(self, *, tools: tuple[ToolDefinition, ...], policy: StageToolPolicy) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._policy = policy
        self._audit_log: list[ToolAuditEntry] = []

    @property
    def audit_log(self) -> tuple[ToolAuditEntry, ...]:
        return tuple(self._audit_log)

    def execute(self, call: ToolCall) -> ToolResult:
        definition = self._tools.get(call.name)
        if definition is None:
            raise ToolNotFoundError(f"tool {call.name!r} is not registered")
        self._policy.check(call, definition)
        try:
            output = definition.handler(call)
        except Exception as exc:
            error = str(exc)
            self._audit_log.append(
                ToolAuditEntry(
                    stage=call.stage,
                    name=call.name,
                    correlation_id=call.correlation_id,
                    ok=False,
                    error=error,
                )
            )
            return ToolResult(call=call, ok=False, error=error)

        self._audit_log.append(
            ToolAuditEntry(
                stage=call.stage,
                name=call.name,
                correlation_id=call.correlation_id,
                ok=True,
            )
        )
        return ToolResult(call=call, ok=True, output=output)
