"""Tests for GitHub webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from src.adapters.connectors.github import verify_signature

SECRET = "sssh-its-a-secret"
BODY = b'{"action":"opened","number":1}'


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_signature():
    assert verify_signature(SECRET, BODY, _sign(SECRET, BODY)) is True


def test_verify_signature_rejects_wrong_secret():
    bad = _sign("other-secret", BODY)
    assert verify_signature(SECRET, BODY, bad) is False


def test_verify_signature_rejects_modified_body():
    sig = _sign(SECRET, BODY)
    assert verify_signature(SECRET, BODY + b" ", sig) is False


def test_verify_signature_rejects_missing_header():
    assert verify_signature(SECRET, BODY, None) is False
    assert verify_signature(SECRET, BODY, "") is False


def test_verify_signature_rejects_missing_secret():
    assert verify_signature("", BODY, _sign(SECRET, BODY)) is False


def test_verify_signature_rejects_wrong_prefix():
    sig = _sign(SECRET, BODY).replace("sha256=", "sha1=")
    assert verify_signature(SECRET, BODY, sig) is False


def test_verify_signature_rejects_garbage_header():
    assert verify_signature(SECRET, BODY, "not-a-signature") is False
    assert verify_signature(SECRET, BODY, "sha256=") is False
    assert verify_signature(SECRET, BODY, "sha256=zz" * 32) is False


def test_verify_signature_handles_empty_body():
    sig = _sign(SECRET, b"")
    assert verify_signature(SECRET, b"", sig) is True
