"""Tests for structured logging field allowlist."""

from __future__ import annotations

import io
import json

from src.shared import get_logger, setup_logging


def test_json_formatter_includes_agent_runtime_health_fields_without_credentials() -> None:
    stream = io.StringIO()
    setup_logging(fmt="json", stream=stream)

    get_logger("tests.logging").info(
        "agent runtime health checked",
        extra={
            "agent_runtime_provider": "openai-compatible",
            "agent_runtime_status": "supported",
            "agent_runtime_warnings": ("Live provider smoke check not executed",),
        },
    )

    payload = json.loads(stream.getvalue())

    assert payload["agent_runtime_provider"] == "openai-compatible"
    assert payload["agent_runtime_status"] == "supported"
    assert payload["agent_runtime_warnings"] == ["Live provider smoke check not executed"]
