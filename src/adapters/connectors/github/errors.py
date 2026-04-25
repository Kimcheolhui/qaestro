"""GitHub connector errors.

A small hierarchy mapped from HTTP status + headers by the client. Keeping the
classes tiny (no extra fields beyond what the upstream layers need) avoids
leaking raw HTTP details into the domain layer while still letting workers
distinguish auth failures, rate-limits, and not-found in retry/backoff code.
"""

from __future__ import annotations


class GitHubError(Exception):
    """Base class for all GitHub connector errors.

    Attributes:
        status: HTTP status code returned by GitHub (``0`` if no response).
        message: Human-readable detail extracted from the response body.
    """

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class AuthError(GitHubError):
    """Raised on 401/403 responses — bad credentials or insufficient scope."""


class RateLimitError(GitHubError):
    """Raised on 429 or 403 with ``x-ratelimit-remaining: 0``.

    Attributes:
        reset_at: Unix epoch seconds when the rate-limit window resets, or
            ``None`` if the header was missing.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        reset_at: int | None = None,
    ) -> None:
        super().__init__(message, status=status)
        self.reset_at = reset_at


class NotFoundError(GitHubError):
    """Raised on 404 responses."""
