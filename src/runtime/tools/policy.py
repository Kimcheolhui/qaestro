"""Stage policy enforcement for ToolRuntime calls."""

from __future__ import annotations

from collections.abc import Mapping

from src.runtime.stages import WorkflowStage

from .types import ToolCall, ToolCapability, ToolDefinition


class ToolPolicyError(RuntimeError):
    """Raised when a workflow stage is not allowed to execute a tool."""


class StageToolPolicy:
    """Allowlist of tool names and capability classes per workflow stage."""

    def __init__(
        self,
        allowed_tools_by_stage: Mapping[WorkflowStage, tuple[str, ...]],
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
