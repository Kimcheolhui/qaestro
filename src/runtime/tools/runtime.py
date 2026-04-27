"""Deterministic ToolRuntime implementation."""

from __future__ import annotations

from typing import Protocol

from .policy import StageToolPolicy
from .types import ToolAuditEntry, ToolCall, ToolDefinition, ToolResult


class ToolNotFoundError(RuntimeError):
    """Raised when no registered tool matches a requested tool name."""


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
