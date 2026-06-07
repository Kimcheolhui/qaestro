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


def test_json_formatter_redacts_secret_values_from_message_and_allowlisted_extra_fields() -> None:
    stream = io.StringIO()
    setup_logging(fmt="json", stream=stream)

    get_logger("tests.logging").error(
        "worker failed token=qaestro-secret-token",
        extra={
            "error": "provider failed with password=opaque-password-value at https://private.example.test/v1",
            "agent_runtime_warnings": [
                {
                    "client_secret": "structured-client-value",
                    "safe": "visible",
                }
            ],
            "correlation_id": "corr-secret-redaction",
        },
    )

    payload = json.loads(stream.getvalue())
    rendered = json.dumps(payload)

    assert "qaestro-secret-token" not in rendered
    assert "opaque-password-value" not in rendered
    assert "structured-client-value" not in rendered
    assert "private.example.test" not in rendered
    assert payload["msg"] == "worker failed token=<redacted>"
    assert payload["error"] == "provider failed with password=<redacted> at <redacted-url>"
    assert payload["agent_runtime_warnings"] == [{"client_secret": "<redacted>", "safe": "visible"}]


def test_text_formatter_redacts_secret_values_from_messages() -> None:
    stream = io.StringIO()
    setup_logging(fmt="text", stream=stream)

    get_logger("tests.logging").error("worker failed token=qaestro-secret-token at https://private.example.test/v1")

    rendered = stream.getvalue()
    assert "qaestro-secret-token" not in rendered
    assert "private.example.test" not in rendered
    assert "worker failed token=<redacted> at <redacted-url>" in rendered
