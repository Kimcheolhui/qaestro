"""GitHub connector — webhook verification, App auth, REST client.

Public surface:

- :class:`GitHubAppAuth` — short-lived JWT + installation token issuance.
- :class:`GitHubClient` — typed wrapper over the small subset of REST endpoints
  qaestro currently calls (PR metadata, file list, diff, issue comments).
- :func:`verify_signature` — HMAC-SHA256 webhook signature verification.
- :class:`HTTPTransport` / :class:`UrllibTransport` — pluggable HTTP layer to
  enable test fakes without monkeypatching ``urllib``.
- Error hierarchy: :class:`GitHubError`, :class:`AuthError`,
  :class:`RateLimitError`, :class:`NotFoundError`.

The connector deliberately speaks **only** in terms of small frozen dataclasses
defined in :mod:`.types`; downstream modules never see raw ``dict`` payloads.
"""

from .auth import Clock, GitHubAppAuth, SystemClock
from .client import GitHubClient
from .errors import AuthError, GitHubError, NotFoundError, RateLimitError
from .transport import FakeResponse, FakeTransport, HTTPResponse, HTTPTransport, UrllibTransport
from .types import CommentResult, FileDiff, PRMeta
from .webhook import verify_signature

__all__ = [
    "AuthError",
    "Clock",
    "CommentResult",
    "FakeResponse",
    "FakeTransport",
    "FileDiff",
    "GitHubAppAuth",
    "GitHubClient",
    "GitHubError",
    "HTTPResponse",
    "HTTPTransport",
    "NotFoundError",
    "PRMeta",
    "RateLimitError",
    "SystemClock",
    "UrllibTransport",
    "verify_signature",
]
