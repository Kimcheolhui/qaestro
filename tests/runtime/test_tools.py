"""Tests for workflow ToolRuntime contracts and policy enforcement."""

from __future__ import annotations

import pytest

from src.runtime.tools import (
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCall,
    ToolCapability,
    ToolDefinition,
    ToolPolicyError,
)


def test_registered_tool_runtime_executes_allowed_tool_and_records_audit_log() -> None:
    runtime = RegisteredToolRuntime(
        tools=(
            ToolDefinition(
                name="demo.read",
                capabilities=(ToolCapability.READ,),
                handler=lambda call: {"value": call.input["value"]},
            ),
        ),
        policy=StageToolPolicy({"context": ("demo.read",)}),
    )

    result = runtime.execute(
        ToolCall(
            stage="context",
            name="demo.read",
            input={"value": "ok"},
            correlation_id="corr-tools",
        )
    )

    assert result.ok is True
    assert result.output == {"value": "ok"}
    assert result.error == ""
    assert [(entry.stage, entry.name, entry.correlation_id, entry.ok) for entry in runtime.audit_log] == [
        ("context", "demo.read", "corr-tools", True)
    ]


def test_registered_tool_runtime_rejects_tools_not_allowed_for_stage() -> None:
    runtime = RegisteredToolRuntime(
        tools=(
            ToolDefinition(
                name="demo.write",
                capabilities=(ToolCapability.WRITE,),
                handler=lambda call: None,
            ),
        ),
        policy=StageToolPolicy({"context": ("demo.read",)}),
    )

    with pytest.raises(ToolPolicyError, match="not allowed"):
        runtime.execute(ToolCall(stage="context", name="demo.write", input={}, correlation_id="corr-denied"))

    assert runtime.audit_log == ()


def test_registered_tool_runtime_denies_destructive_tools_by_default() -> None:
    runtime = RegisteredToolRuntime(
        tools=(
            ToolDefinition(
                name="demo.delete",
                capabilities=(ToolCapability.DESTRUCTIVE,),
                handler=lambda call: "deleted",
            ),
        ),
        policy=StageToolPolicy({"output": ("demo.delete",)}),
    )

    with pytest.raises(ToolPolicyError, match="destructive"):
        runtime.execute(ToolCall(stage="output", name="demo.delete", input={}, correlation_id="corr-danger"))

    assert runtime.audit_log == ()
