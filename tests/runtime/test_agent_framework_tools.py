"""Tests for Microsoft Agent Framework-facing ToolRuntime adapters."""

from __future__ import annotations

import pytest

from src.runtime.stages import WorkflowStage
from src.runtime.tools import (
    AgentFrameworkToolAdapter,
    AgentFrameworkToolSpec,
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCall,
    ToolCapability,
    ToolDefinition,
    ToolPolicyError,
)


def _tool_definitions() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="demo.read",
            description="Read demo data through a stage-approved qaestro tool.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            capabilities=(ToolCapability.READ,),
            handler=lambda call: {"stage": call.stage.value, "value": call.input["value"]},
        ),
        ToolDefinition(
            name="demo.write",
            description="Write demo data through the output stage.",
            input_schema={"type": "object", "properties": {}},
            capabilities=(ToolCapability.WRITE,),
            handler=lambda call: {"wrote": True},
        ),
    )


def _adapter() -> AgentFrameworkToolAdapter:
    tools = _tool_definitions()
    policy = StageToolPolicy(
        {
            WorkflowStage.CONTEXT: ("demo.read",),
            WorkflowStage.OUTPUT: ("demo.write",),
        }
    )
    runtime = RegisteredToolRuntime(tools=tools, policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=tools, policy=policy)


def test_agent_framework_adapter_exposes_only_stage_approved_tool_specs() -> None:
    adapter = _adapter()

    specs = adapter.tool_specs_for_stage(WorkflowStage.CONTEXT)

    assert specs == (
        AgentFrameworkToolSpec(
            name="demo.read",
            description="Read demo data through a stage-approved qaestro tool.",
            parameters_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            stage=WorkflowStage.CONTEXT,
            capabilities=(ToolCapability.READ,),
        ),
    )


def test_agent_framework_adapter_invokes_tool_runtime_with_stage_and_correlation() -> None:
    adapter = _adapter()

    result = adapter.invoke(
        stage=WorkflowStage.CONTEXT,
        name="demo.read",
        arguments={"value": "ok"},
        correlation_id="corr-agent-framework",
    )

    assert result.ok is True
    assert result.output == {"stage": "context", "value": "ok"}
    assert result.call == ToolCall(
        stage=WorkflowStage.CONTEXT,
        name="demo.read",
        input={"value": "ok"},
        correlation_id="corr-agent-framework",
    )


def test_agent_framework_adapter_keeps_stage_policy_as_guardrail() -> None:
    adapter = _adapter()

    with pytest.raises(ToolPolicyError, match="not allowed"):
        adapter.invoke(
            stage=WorkflowStage.CONTEXT,
            name="demo.write",
            arguments={},
            correlation_id="corr-agent-framework-denied",
        )
