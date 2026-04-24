"""Pluggable HTTP transport.

The connector talks to GitHub through a thin :class:`HTTPTransport` Protocol
so tests can substitute a deterministic fake without monkeypatching ``urllib``.

Production uses :class:`UrllibTransport` (stdlib only — see
``docs/TECH_DECISIONS.md``). If we later need connection pooling, retries with
jitter, or HTTP/2, swapping in an ``httpx``-backed transport is a one-class
change with no impact on the rest of the codebase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise urlerror.HTTPError(req.full_url, code, msg, headers, fp)


_NO_REDIRECT_OPENER = urlrequest.build_opener(_NoRedirect)


@dataclass(frozen=True)
class HTTPResponse:
    """Minimal response container returned by :class:`HTTPTransport`."""

    status: int
    headers: dict[str, str]  # lowercase keys
    body: bytes

    def json(self) -> object:
        """Decode the body as JSON. Empty body → ``None``."""
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class HTTPTransport(Protocol):
    """Synchronous HTTP transport interface.

    Implementations MUST return :class:`HTTPResponse` for every status code
    (including 4xx/5xx). Network errors should raise :class:`OSError`.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HTTPResponse: ...


class UrllibTransport:
    """stdlib-only HTTP transport built on :mod:`urllib.request`."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HTTPResponse:
        req = urlrequest.Request(url, data=body, method=method.upper())
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        try:
            with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
                # The opener deliberately fails closed on 3xx so sensitive
                # Authorization headers are never forwarded to redirect targets.
                return HTTPResponse(
                    status=resp.status,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except urlerror.HTTPError as e:
            # HTTPError is a Response too — read body for error detail.
            body_bytes = e.read() if hasattr(e, "read") else b""
            return HTTPResponse(
                status=e.code,
                headers={k.lower(): v for k, v in (e.headers or {}).items()},
                body=body_bytes,
            )


# ── Test fakes ────────────────────────────────────────────────────────────


@dataclass
class FakeResponse:
    """Programmable response for :class:`FakeTransport`."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class _RecordedCall:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


class FakeTransport:
    """In-memory transport for tests.

    Configure responses with :meth:`enqueue` (FIFO) or :meth:`route` (per
    method+URL). Inspect outbound calls via :attr:`calls`.
    """

    def __init__(self) -> None:
        self.calls: list[_RecordedCall] = []
        self._queue: list[FakeResponse] = []
        self._routes: dict[tuple[str, str], list[FakeResponse]] = {}

    def enqueue(self, response: FakeResponse) -> None:
        """Queue a response to return on the next request (any method/URL)."""
        self._queue.append(response)

    def route(self, method: str, url: str, response: FakeResponse) -> None:
        """Pin a response to a (method, url) pair. Multiple calls FIFO."""
        self._routes.setdefault((method.upper(), url), []).append(response)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HTTPResponse:
        del timeout  # unused
        self.calls.append(
            _RecordedCall(
                method=method.upper(),
                url=url,
                headers=dict(headers or {}),
                body=body,
            )
        )

        key = (method.upper(), url)
        if self._routes.get(key):
            r = self._routes[key].pop(0)
        elif self._queue:
            r = self._queue.pop(0)
        else:
            raise AssertionError(f"FakeTransport: no response configured for {method.upper()} {url}")
        return HTTPResponse(status=r.status, headers={k.lower(): v for k, v in r.headers.items()}, body=r.body)
