"""PR context acquisition for workflow orchestration."""

from __future__ import annotations

from typing import Protocol

from src.core.analyzer import PRAnalysisContext, PRFileDiff, PRFileStatus
from src.core.contracts import PREvent


class PRContextProvider(Protocol):
    """Loads normalized PR analysis context for a PR event."""

    def load(self, event: PREvent) -> PRAnalysisContext: ...


class EventPRContextProvider:
    """Fallback provider using only lightweight event fields.

    This keeps local/in-memory tests side-effect free. Durable worker wiring can
    inject a provider from the worker/adapter layer to fetch real metadata/files/diff.
    """

    def load(self, event: PREvent) -> PRAnalysisContext:
        return PRAnalysisContext(
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            title=event.title,
            body=event.body,
            base_branch=event.base_branch,
            head_branch=event.head_branch,
            files=tuple(
                PRFileDiff(
                    path=file.path,
                    status=PRFileStatus.normalize(file.status),
                    additions=file.additions,
                    deletions=file.deletions,
                    previous_filename=file.previous_filename,
                )
                for file in event.files_changed
            ),
            unified_diff="",
        )
