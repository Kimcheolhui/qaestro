"""Tests for centralized secret redaction."""

from __future__ import annotations

from src.shared.redaction import SecretRedactor, redact_text


def test_redact_text_removes_common_secret_shapes_without_manual_callsite_patterns() -> None:
    raw = "token=qaestro-secret-token password:opaque-password-value api_key='opaque-api-token' Authorization: Bearer opaque...ken"

    redacted = redact_text(raw)

    assert "qaestro-secret-token" not in redacted
    assert "opaque-password-value" not in redacted
    assert "opaque-api-token" not in redacted
    assert "opaque...ken" not in redacted
    assert redacted.count("<redacted>") >= 4


def test_secret_redactor_can_redact_explicit_runtime_secret_and_urls_for_external_output() -> None:
    redactor = SecretRedactor(explicit_secrets=("runtime-secret-value",), redact_urls=True)

    redacted = redactor.redact_text(
        "provider failed at https://private.example.test/v1 with runtime-secret-value and credential=abc123"
    )

    assert "runtime-secret-value" not in redacted
    assert "private.example.test" not in redacted
    assert "abc123" not in redacted
    assert "<redacted-url>" in redacted


def test_redact_text_redacts_url_userinfo_password_without_hiding_host() -> None:
    redacted = redact_text("redis://:redis-secret-password@redis.example.test:6379/0")

    assert redacted == "redis://:<redacted>@redis.example.test:6379/0"
    assert "redis-secret-password" not in redacted


def test_redact_text_redacts_url_userinfo_username_with_password_without_hiding_host() -> None:
    redacted = redact_text("postgres://db-user:db-secret-password@db.example.test:5432/app")

    assert redacted == "postgres://<redacted-userinfo>@db.example.test:5432/app"
    assert "db-user" not in redacted
    assert "db-secret-password" not in redacted


def test_secret_redactor_recurses_through_serializable_structures() -> None:
    redactor = SecretRedactor(explicit_secrets=("runtime-secret-value",), redact_urls=True)

    redacted = redactor.redact_value(
        {
            "error": "token=runtime-secret-value",
            "nested": ["password=opaque-password-value", {"url": "https://private.example.test/path"}],
        }
    )

    rendered = repr(redacted)
    assert "runtime-secret-value" not in rendered
    assert "opaque-password-value" not in rendered
    assert "private.example.test" not in rendered


def test_redact_text_redacts_json_and_dict_style_secret_fields() -> None:
    raw = (
        '{"client_secret":"json-client-value", "AWS_SECRET_ACCESS_KEY":"aws-secret-value", '
        "'password': 'dict-password-value', 'Authorization': 'Basic quoted-auth-value'}"
    )

    redacted = redact_text(raw)

    assert "json-client-value" not in redacted
    assert "aws-secret-value" not in redacted
    assert "dict-password-value" not in redacted
    assert "quoted-auth-value" not in redacted
    assert '"client_secret":"<redacted>"' in redacted
    assert "'password': '<redacted>'" in redacted


def test_redact_text_redacts_authorization_assignment_forms() -> None:
    redacted = redact_text("Authorization=Basic assignment-basic-token AUTHORIZATION=Bearer assignment-bearer-token")

    assert "assignment-basic-token" not in redacted
    assert "assignment-bearer-token" not in redacted
    assert redacted == "Authorization=<redacted> AUTHORIZATION=<redacted>"


def test_secret_redactor_redacts_values_when_mapping_keys_are_secret_like() -> None:
    redactor = SecretRedactor(redact_urls=True)

    redacted = redactor.redact_value(
        {
            "client_secret": "structured-client-value",
            "headers": {"Authorization": "Basic structured-auth-value"},
            "safe": "visible",
        }
    )

    rendered = repr(redacted)
    assert "structured-client-value" not in rendered
    assert "structured-auth-value" not in rendered
    assert "visible" in rendered
