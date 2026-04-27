"""Input types for PR behaviour analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PRFileStatus(StrEnum):
    """Provider-neutral file lifecycle status for a PR file diff."""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"

    @classmethod
    def normalize(cls, value: str | PRFileStatus) -> PRFileStatus:
        """Map provider strings to the closest normalized status."""
        if isinstance(value, PRFileStatus):
            return value
        normalized = value.strip().lower()
        aliases = {
            "added": cls.ADDED,
            "created": cls.ADDED,
            "modified": cls.MODIFIED,
            "changed": cls.CHANGED,
            "removed": cls.REMOVED,
            "deleted": cls.REMOVED,
            "renamed": cls.RENAMED,
            "copied": cls.COPIED,
            "unchanged": cls.UNCHANGED,
        }
        return aliases.get(normalized, cls.UNKNOWN)


@dataclass(frozen=True)
class PRFileDiff:
    """A normalized file diff used by the Behaviour Analyzer.

    ``path`` is the current PR-side file path. For renamed files, the old path is
    stored separately in ``previous_filename``. ``patch`` is the optional unified
    diff hunk for this single file; providers may omit it for binary/large files.
    """

    path: str
    status: PRFileStatus
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    previous_filename: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PRFileStatus.normalize(self.status))


@dataclass(frozen=True)
class PRAnalysisContext:
    """Normalized PR context consumed by core analyzer logic."""

    repo_full_name: str
    pr_number: int
    title: str
    body: str
    base_branch: str
    head_branch: str
    files: tuple[PRFileDiff, ...]
    unified_diff: str = ""

    @staticmethod
    def file(
        *,
        path: str,
        status: str | PRFileStatus,
        additions: int = 0,
        deletions: int = 0,
        patch: str | None = None,
        previous_filename: str = "",
    ) -> PRFileDiff:
        """Small convenience constructor for tests and simple context providers."""
        return PRFileDiff(
            path=path,
            status=PRFileStatus.normalize(status),
            additions=additions,
            deletions=deletions,
            patch=patch,
            previous_filename=previous_filename,
        )
