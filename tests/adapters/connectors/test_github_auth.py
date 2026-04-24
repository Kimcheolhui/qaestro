"""Tests for GitHub App authentication (JWT + installation token caching)."""

from __future__ import annotations

import json
import threading
from datetime import UTC

import jwt
import pytest

from src.adapters.connectors.github import GitHubAppAuth
from src.adapters.connectors.github.errors import AuthError, GitHubError, RateLimitError
from src.adapters.connectors.github.transport import FakeResponse, FakeTransport

APP_ID = 12345
INSTALL_ID = 99999
TOKEN_URL = f"https://api.github.com/app/installations/{INSTALL_ID}/access_tokens"


class ManualClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture
def private_key(github_app_private_key_pem: bytes) -> str:
    return github_app_private_key_pem.decode()


@pytest.fixture
def public_key(private_key: str) -> str:
    from cryptography.hazmat.primitives import serialization

    priv = serialization.load_pem_private_key(private_key.encode(), password=None)
    return (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def _make_token_response(token: str = "ghs_abc123", expires_in_seconds: int = 3600) -> FakeResponse:
    # GitHub returns expires_at as ISO-8601 Z. Build one offset from a fixed
    # reference matching ManualClock's start time.
    from datetime import datetime, timedelta

    base = datetime.fromtimestamp(1_700_000_000.0, tz=UTC)
    expires = base + timedelta(seconds=expires_in_seconds)
    body = json.dumps({"token": token, "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}).encode()
    return FakeResponse(status=201, body=body)


def test_app_jwt_is_signed_with_rs256_and_decodable(private_key, public_key):
    clock = ManualClock()
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        clock=clock,
    )
    token = auth.app_jwt()
    decoded = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_iat": False, "verify_exp": False},
    )
    assert decoded["iss"] == str(APP_ID)
    # iat is back-dated 60 s for clock skew
    assert decoded["iat"] == int(clock.now()) - 60
    # exp ~ 9 minutes ahead
    assert decoded["exp"] - decoded["iat"] == 9 * 60 + 60


def test_installation_token_exchange_succeeds(private_key):
    clock = ManualClock()
    transport = FakeTransport()
    transport.route("POST", TOKEN_URL, _make_token_response("ghs_first"))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=clock,
    )
    assert auth.installation_token() == "ghs_first"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call.method == "POST"
    assert call.headers["Accept"] == "application/vnd.github+json"
    assert call.headers["Authorization"].startswith("Bearer ")


def test_installation_token_is_cached(private_key):
    clock = ManualClock()
    transport = FakeTransport()
    transport.enqueue(_make_token_response("ghs_first", expires_in_seconds=3600))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=clock,
    )
    assert auth.installation_token() == "ghs_first"
    # 30 minutes later — still well within the cache window
    clock.advance(1800)
    assert auth.installation_token() == "ghs_first"
    assert len(transport.calls) == 1  # no second exchange


def test_installation_token_refreshes_within_skew_window(private_key):
    clock = ManualClock()
    transport = FakeTransport()
    transport.enqueue(_make_token_response("ghs_first", expires_in_seconds=3600))
    transport.enqueue(_make_token_response("ghs_second", expires_in_seconds=3600))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=clock,
    )
    auth.installation_token()
    # Jump to 30 s before expiry (well inside the 60 s safety margin)
    clock.advance(3600 - 30)
    assert auth.installation_token() == "ghs_second"
    assert len(transport.calls) == 2


def test_installation_token_concurrent_refresh_serialised(private_key):
    """Concurrent callers must trigger only ONE token exchange."""
    clock = ManualClock()
    transport = FakeTransport()
    # Enqueue more responses than we expect to use — assert only 1 is consumed.
    for i in range(8):
        transport.enqueue(_make_token_response(f"ghs_{i}", expires_in_seconds=3600))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=clock,
    )

    barrier = threading.Barrier(8)
    results: list[str] = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        token = auth.installation_token()
        with lock:
            results.append(token)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert len(set(results)) == 1, f"all callers should see same token, got {set(results)}"
    assert len(transport.calls) == 1, f"expected 1 exchange, got {len(transport.calls)}"


def test_installation_token_auth_error_on_401(private_key):
    transport = FakeTransport()
    transport.enqueue(FakeResponse(status=401, body=b'{"message":"bad creds"}'))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    with pytest.raises(AuthError) as ei:
        auth.installation_token()
    assert ei.value.status == 401


def test_installation_token_rate_limit_on_429(private_key):
    transport = FakeTransport()
    transport.enqueue(
        FakeResponse(
            status=429,
            headers={"Retry-After": "30"},
            body=b'{"message":"Too many installation token requests"}',
        )
    )
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    with pytest.raises(RateLimitError) as ei:
        auth.installation_token()
    assert ei.value.status == 429


def test_installation_token_generic_error_on_500(private_key):
    transport = FakeTransport()
    transport.enqueue(FakeResponse(status=500, body=b"oops"))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    with pytest.raises(GitHubError) as ei:
        auth.installation_token()
    assert ei.value.status == 500
    assert not isinstance(ei.value, AuthError)


def test_installation_token_malformed_json_raises(private_key):
    transport = FakeTransport()
    transport.enqueue(FakeResponse(status=201, body=b"not json"))
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    with pytest.raises(GitHubError):
        auth.installation_token()


def test_installation_token_missing_fields_raises(private_key):
    transport = FakeTransport()
    transport.enqueue(FakeResponse(status=201, body=b'{"token":"x"}'))  # no expires_at
    auth = GitHubAppAuth(
        app_id=APP_ID,
        private_key=private_key,
        installation_id=INSTALL_ID,
        transport=transport,
        clock=ManualClock(),
    )
    with pytest.raises(GitHubError):
        auth.installation_token()


def test_constructor_validation():
    with pytest.raises(ValueError):
        GitHubAppAuth(app_id=0, private_key="x", installation_id=1)
    with pytest.raises(ValueError):
        GitHubAppAuth(app_id=1, private_key="x", installation_id=0)
    with pytest.raises(ValueError):
        GitHubAppAuth(app_id=1, private_key="", installation_id=1)
