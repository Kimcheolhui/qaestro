"""Shared fixtures for connector tests."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def github_app_private_key_pem() -> bytes:
    """Generate an ephemeral RSA key for GitHub App auth tests.

    Generated in-process per test session — never persisted to disk, never
    committed. Avoids checking key material (even test-only) into the repo,
    which secret scanners flag.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
