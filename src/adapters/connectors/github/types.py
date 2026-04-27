"""Frozen domain types returned by :class:`GitHubClient`.

These are intentionally minimal — only the fields qaestro currently consumes.
Adding fields is cheap, but we don't want to mirror GitHub's API shape
verbatim and lock callers to it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PRMeta:
    """Pull request metadata snapshot."""

    number: int
    title: str
    state: str  # "open" | "closed"
    head_sha: str
    base_ref: str
    head_ref: str
    author: str
    draft: bool
    html_url: str


@dataclass(frozen=True)
class FileDiff:
    """Per-file change summary as returned by ``GET /pulls/:n/files``."""

    filename: str
    status: str  # "added" | "modified" | "removed" | "renamed" | "copied"
    additions: int
    deletions: int
    changes: int
    patch: str | None  # absent for binary or very large diffs
    previous_filename: str = ""  # populated when status == "renamed"


@dataclass(frozen=True)
class CommentResult:
    """Result of creating, updating, or reading an issue/PR comment."""

    id: int
    html_url: str
    body: str = ""
