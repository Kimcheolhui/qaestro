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

    def allowed_tool_names(self, stage: WorkflowStage) -> tuple[str, ...]:
        """Return tool names explicitly exposed to an agent runner for a stage."""
        return tuple(sorted(self._allowed_tools_by_stage.get(stage, frozenset())))

    def denial_reason(self, *, stage: WorkflowStage, name: str, definition: ToolDefinition) -> str:
        """Return a policy-denial reason, or an empty string when allowed."""
        allowed_tools = self._allowed_tools_by_stage.get(stage, frozenset())
        if name not in allowed_tools:
            return f"tool {name!r} is not allowed during {stage!r} stage"
        if ToolCapability.DESTRUCTIVE in definition.capabilities and not self._allow_destructive:
            return f"destructive tool {name!r} is denied by default"
        if stage is WorkflowStage.VALIDATOR and ToolCapability.WRITE in definition.capabilities:
            return f"write capability on tool {name!r} is denied during validator stage"
        return ""

    def check(self, call: ToolCall, definition: ToolDefinition) -> None:
        denial = self.denial_reason(stage=call.stage, name=call.name, definition=definition)
        if denial:
            raise ToolPolicyError(denial)
