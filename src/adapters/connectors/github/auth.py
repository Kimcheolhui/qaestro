"""GitHub App authentication.

Two-step token issuance:

1. Build a short-lived **App JWT** (≤ 10 min) signed with the App's private
   key (RS256). The JWT proves "I am App #X".
2. Exchange the JWT for an **installation access token** at
   ``POST /app/installations/{id}/access_tokens``. The returned token (~1 hour
   lifetime) is what the REST client puts in ``Authorization: Bearer`` headers
   for the actual API calls.

We cache the installation token in memory until 60 s before its ``expires_at``
to avoid hammering the auth endpoint while still leaving a safety margin for
clock skew and slow network calls. A :class:`threading.Lock` serialises the
refresh path so concurrent worker threads don't all kick off a new exchange
simultaneously.

Time is read through a :class:`Clock` Protocol so tests can advance "now"
without ``time.sleep`` or ``freezegun``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import jwt  # PyJWT[crypto]

from .errors import AuthError, GitHubError, RateLimitError
from .transport import HTTPResponse, HTTPTransport, UrllibTransport

# Safety margin: refresh installation tokens 60 s before stated expiry.
_TOKEN_SKEW_SECONDS = 60

# JWT lifetime: GitHub allows up to 10 min; we issue 9 min and clamp ``iat``
# 60 s in the past to tolerate small clock drift between us and GitHub.
_JWT_IAT_SKEW_SECONDS = 60
_JWT_LIFETIME_SECONDS = 9 * 60


class Clock(Protocol):
    """Minimal clock abstraction — returns POSIX seconds (float)."""

    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


@dataclass(frozen=True)
class _CachedToken:
    token: str
    expires_at: float  # POSIX seconds


class GitHubAppAuth:
    """Issue and cache installation tokens for a single GitHub App install.

    Args:
        app_id: Numeric GitHub App ID.
        private_key: PEM-encoded RSA private key (string or bytes).
        installation_id: Numeric installation ID for the target org/repo.
        transport: HTTP transport used for the token exchange. Defaults to
            :class:`UrllibTransport`.
        clock: Time source. Defaults to :class:`SystemClock`.
        api_base: GitHub REST API base URL. Override for GitHub Enterprise.
    """

    def __init__(
        self,
        *,
        app_id: int,
        private_key: str | bytes,
        installation_id: int,
        transport: HTTPTransport | None = None,
        clock: Clock | None = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        if app_id <= 0:
            raise ValueError("app_id must be a positive integer")
        if installation_id <= 0:
            raise ValueError("installation_id must be a positive integer")
        if not private_key:
            raise ValueError("private_key must not be empty")

        self._app_id = app_id
        self._private_key = private_key
        self._installation_id = installation_id
        self._transport = transport or UrllibTransport()
        self._clock = clock or SystemClock()
        self._api_base = api_base.rstrip("/")
        self._lock = threading.Lock()
        self._cached: _CachedToken | None = None

    # ── Public API ────────────────────────────────────────────────────

    def app_jwt(self) -> str:
        """Build a fresh RS256-signed App JWT.

        The JWT is *not* cached — it's cheap to generate and a fresh one keeps
        the validity window aligned with the current wall clock.
        """
        now = int(self._clock.now())
        payload = {
            "iat": now - _JWT_IAT_SKEW_SECONDS,
            "exp": now + _JWT_LIFETIME_SECONDS,
            "iss": str(self._app_id),
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    def installation_token(self) -> str:
        """Return a valid installation token, refreshing if necessary."""
        now = self._clock.now()

        # Fast path: cached token still valid (no lock needed for the read —
        # ``_cached`` is only ever replaced atomically under the lock).
        cached = self._cached
        if cached is not None and cached.expires_at - _TOKEN_SKEW_SECONDS > now:
            return cached.token

        with self._lock:
            # Re-check under the lock — another thread may have refreshed.
            cached = self._cached
            now = self._clock.now()
            if cached is not None and cached.expires_at - _TOKEN_SKEW_SECONDS > now:
                return cached.token

            self._cached = self._exchange_for_installation_token()
            return self._cached.token

    # ── Internal ──────────────────────────────────────────────────────

    def _exchange_for_installation_token(self) -> _CachedToken:
        url = f"{self._api_base}/app/installations/{self._installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {self.app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qaestro",
        }
        resp = self._transport.request("POST", url, headers=headers, body=b"")
        _raise_for_status(resp)

        try:
            data = json.loads(resp.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise GitHubError(
                f"installation token response was not valid JSON: {e}",
                status=resp.status,
            ) from e

        token = data.get("token")
        expires_at_raw = data.get("expires_at")
        if not token or not expires_at_raw:
            raise GitHubError(
                "installation token response missing 'token' or 'expires_at'",
                status=resp.status,
            )

        expires_at = _parse_iso8601_z(expires_at_raw)
        return _CachedToken(token=token, expires_at=expires_at)


def _raise_for_status(resp: HTTPResponse) -> None:
    if resp.status < 400:
        return

    detail = resp.text()[:200] if resp.body else ""
    if resp.status == 429 or _is_rate_limited(resp, detail):
        raise RateLimitError(
            f"installation token exchange rate limited (status={resp.status}): {detail}",
            status=resp.status,
            reset_at=_int_header(_header(resp, "x-ratelimit-reset")),
        )
    if resp.status in (401, 403):
        raise AuthError(
            f"GitHub App auth rejected (status={resp.status}): {detail}",
            status=resp.status,
        )
    raise GitHubError(
        f"installation token exchange failed (status={resp.status}): {detail}",
        status=resp.status,
    )


def _is_rate_limited(resp: HTTPResponse, detail: str) -> bool:
    remaining = _header(resp, "x-ratelimit-remaining")
    if remaining == "0" or _header(resp, "retry-after") is not None:
        return True
    lowered = detail.lower()
    return "rate limit" in lowered or "abuse detection" in lowered


def _header(resp: HTTPResponse, name: str) -> str | None:
    return resp.headers.get(name.lower())


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_iso8601_z(value: str) -> float:
    """Parse GitHub's ``2024-01-01T12:00:00Z`` timestamps to POSIX seconds."""
    # ``datetime.fromisoformat`` accepts ``+00:00`` but not the trailing ``Z``
    # before Python 3.11 in all paths — normalise for safety.
    normalised = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalised)
    except ValueError as e:
        raise GitHubError(f"invalid expires_at timestamp: {value!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()
