"""Event types for devclaw's event-driven architecture.

All events are frozen dataclasses representing normalized webhook payloads
from GitHub, Slack, Teams, and other integration sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, unique


@unique
class EventType(Enum):
    """Discriminator for all event kinds flowing through the system."""

    PR_OPENED = "pr_opened"
    PR_UPDATED = "pr_updated"
    PR_COMMENTED = "pr_commented"
    PR_REVIEWED = "pr_reviewed"
    CI_COMPLETED = "ci_completed"
    CHAT_MENTION = "chat_mention"


@dataclass(frozen=True)
class EventMeta:
    """Common metadata attached to every event."""

    event_id: str
    event_type: EventType
    correlation_id: str
    timestamp: datetime
    source: str


@dataclass(frozen=True)
class FileChange:
    """A single file changed in a pull request."""

    path: str
    status: str  # "added", "modified", "removed", "renamed"
    additions: int = 0
    deletions: int = 0
    patch: str = ""


@dataclass(frozen=True)
class PROpened:
    """A pull request was opened."""

    meta: EventMeta
    repo_full_name: str
    pr_number: int
    title: str
    body: str
    author: str
    base_branch: str
    head_branch: str
    diff_url: str
    files_changed: tuple[FileChange, ...] = ()


@dataclass(frozen=True)
class PRUpdated:
    """A pull request was updated (new commits pushed, rebased, etc.)."""

    meta: EventMeta
    repo_full_name: str
    pr_number: int
    title: str
    body: str
    author: str
    base_branch: str
    head_branch: str
    diff_url: str
    files_changed: tuple[FileChange, ...] = ()


@dataclass(frozen=True)
class PRCommented:
    """A comment was posted on a pull request."""

    meta: EventMeta
    repo_full_name: str
    pr_number: int
    comment_id: int
    author: str
    body: str
    is_review_comment: bool = False
    path: str = ""
    line: int | None = None


@dataclass(frozen=True)
class PRReviewed:
    """A pull request review was submitted."""

    meta: EventMeta
    repo_full_name: str
    pr_number: int
    reviewer: str
    state: str  # "approved", "changes_requested", "commented"
    body: str = ""


@dataclass(frozen=True)
class CICompleted:
    """A CI workflow run completed."""

    meta: EventMeta
    repo_full_name: str
    pr_number: int | None
    commit_sha: str
    workflow_name: str
    conclusion: str  # "success", "failure", "cancelled", "timed_out"
    run_url: str
    failed_jobs: tuple[str, ...] = ()
    logs_url: str = ""


@dataclass(frozen=True)
class ChatMention:
    """The bot was mentioned in a chat channel."""

    meta: EventMeta
    platform: str  # "slack", "teams"
    channel_id: str
    channel_name: str
    author: str
    message: str
    thread_id: str = ""
    referenced_pr: int | None = None


# Union of all concrete event types
Event = PROpened | PRUpdated | PRCommented | PRReviewed | CICompleted | ChatMention
