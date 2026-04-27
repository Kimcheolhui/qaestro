"""Tests for runtime.tools package organization."""

from __future__ import annotations

from pathlib import Path

import src.runtime.tools as tools
from src.runtime.tools.policy import StageToolPolicy, ToolPolicyError
from src.runtime.tools.runtime import RegisteredToolRuntime, ToolNotFoundError, ToolRuntime
from src.runtime.tools.types import ToolAuditEntry, ToolCall, ToolCapability, ToolDefinition, ToolResult


def test_runtime_tools_init_only_reexports_public_api() -> None:
    init_path = Path(tools.__file__)
    source = init_path.read_text(encoding="utf-8")

    assert "class " not in source
    assert "@dataclass" not in source
    assert "def " not in source
    assert "from .types import" in source
    assert "from .policy import" in source
    assert "from .runtime import" in source


def test_runtime_tools_public_api_is_reexported_from_focused_modules() -> None:
    assert tools.ToolAuditEntry is ToolAuditEntry
    assert tools.ToolCall is ToolCall
    assert tools.ToolCapability is ToolCapability
    assert tools.ToolDefinition is ToolDefinition
    assert tools.ToolResult is ToolResult
    assert tools.StageToolPolicy is StageToolPolicy
    assert tools.ToolPolicyError is ToolPolicyError
    assert tools.RegisteredToolRuntime is RegisteredToolRuntime
    assert tools.ToolNotFoundError is ToolNotFoundError
    assert tools.ToolRuntime is ToolRuntime
