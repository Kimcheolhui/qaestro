"""Microsoft Agent Framework-facing adapters for qaestro tools.

This module intentionally keeps Agent Framework integration at the seam level.
qaestro owns workflow stage policy, audit, and correlation; an Agent Framework
runner can use these specs/callables as its function-tool bridge without getting
raw access to every registered capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.runtime.stages import WorkflowStage

from .policy import StageToolPolicy
from .runtime import ToolRuntime
from .types import ToolCapability, ToolDefinition, ToolResult


@dataclass(frozen=True)
class AgentFrameworkToolSpec:
    """Framework-neutral function-tool metadata for a stage-approved qaestro tool."""

    name: str
    description: str
    parameters_schema: Mapping[str, Any]
    stage: WorkflowStage
    capabilities: tuple[ToolCapability, ...]


class AgentFrameworkToolAdapter:
    """Expose qaestro ToolRuntime capabilities through an Agent Framework seam.

    Microsoft Agent Framework provides function/tool calling primitives such as
    Python functions wrapped as model-callable tools. This adapter deliberately
    does not import the preview SDK or let the runner bypass qaestro policy. It
    supplies stable tool specs and a single invocation path that still executes
    ``ToolRuntime.execute()`` with the workflow stage and correlation id.
    """

    def __init__(
        self,
        *,
        runtime: ToolRuntime,
        tools: tuple[ToolDefinition, ...],
        policy: StageToolPolicy,
    ) -> None:
        self._runtime = runtime
        self._tools = {tool.name: tool for tool in tools}
        self._policy = policy

    def tool_specs_for_stage(self, stage: WorkflowStage) -> tuple[AgentFrameworkToolSpec, ...]:
        """Return only tool specs that qaestro policy allows for ``stage``."""
        specs: list[AgentFrameworkToolSpec] = []
        for name in self._policy.allowed_tool_names(stage):
            definition = self._tools.get(name)
            if definition is None:
                continue
            specs.append(
                AgentFrameworkToolSpec(
                    name=definition.name,
                    description=definition.description,
                    parameters_schema=definition.input_schema or {"type": "object", "properties": {}},
                    stage=stage,
                    capabilities=definition.capabilities,
                )
            )
        return tuple(specs)

    def invoke(
        self,
        *,
        stage: WorkflowStage,
        name: str,
        arguments: Mapping[str, Any],
        correlation_id: str,
    ) -> ToolResult:
        """Invoke a framework-requested function call through ToolRuntime."""
        from .types import ToolCall

        return self._runtime.execute(
            ToolCall(
                stage=stage,
                name=name,
                input=dict(arguments),
                correlation_id=correlation_id,
            )
        )
