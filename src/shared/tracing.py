"""Lightweight tracing context for correlation across components.

Provides a simple correlation-id mechanism so that all log messages
and API calls within a single event-processing pipeline share a
traceable identifier.  No external dependencies.
"""

from __future__ import annotations

import contextvars
import uuid

# Context variable holding the current correlation id.
# Each async task / thread can have its own value.
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id",
    default="",
)


def new_correlation_id() -> str:
    """Generate and set a new correlation id for the current context.

    Returns the newly created id.
    """
    cid = uuid.uuid4().hex[:16]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """Return the current correlation id, or an empty string if unset."""
    return _correlation_id.get()


def set_correlation_id(cid: str) -> None:
    """Manually set a correlation id (e.g. propagated from an upstream caller)."""
    _correlation_id.set(cid)
