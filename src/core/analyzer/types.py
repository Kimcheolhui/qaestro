"""Input types for PR behaviour analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PRFileDiff:
    """A normalized file diff used by the Behaviour Analyzer.

    This type is provider-neutral on purpose. GitHub-specific file-diff values
    are converted at the runtime/adapters boundary before core analysis runs.
    """

    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    previous_filename: str = ""


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
        status: str,
        additions: int = 0,
        deletions: int = 0,
        patch: str | None = None,
        previous_filename: str = "",
    ) -> PRFileDiff:
        """Small convenience constructor for tests and simple context providers."""
        return PRFileDiff(
            path=path,
            status=status,
            additions=additions,
            deletions=deletions,
            patch=patch,
            previous_filename=previous_filename,
        )
