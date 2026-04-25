"""Renderers turn qaestro results into channel-specific payloads."""

from __future__ import annotations

from .pr_comment import GitHubPRCommentRenderer, PRCommentPayload

__all__ = [
    "GitHubPRCommentRenderer",
    "PRCommentPayload",
]
