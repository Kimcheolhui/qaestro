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


@unique
class EventSource(Enum):
    """Originating system of an event.

    Constrained to a known set so typos in parser/test code fail loudly.
    Extend this enum when adding a new integration (e.g. GitLab, Bitbucket).
    """

    GITHUB = "github"
    SLACK = "slack"
    TEAMS = "teams"
    REPLAY = "replay"  # replayed from a recorded fixture — useful for tests and backfill


@dataclass(frozen=True)
class EventMeta:
    """Common metadata attached to every event."""

    event_id: str
    event_type: EventType
    correlation_id: str
    timestamp: datetime
    source: EventSource


@dataclass(frozen=True)
class FileChange:
    """A single file changed in a pull request.

    Lightweight metadata only — the actual diff text (``patch``) and the
    full file contents are NOT carried on the event.  They are fetched
    on-demand by a separate fetch layer (see Step 2) because:

    * Webhook payloads don't include per-file diffs anyway — they must be
      pulled from ``GET /repos/{owner}/{repo}/pulls/{num}/files``.
    * Events may be persisted / queued / replayed, so keeping them small
      avoids bloating the transport and storage.
    """

    path: str
    status: str  # "added", "modified", "removed", "renamed"
    additions: int = 0
    deletions: int = 0
    previous_filename: str = ""  # populated when status == "renamed"


@dataclass(frozen=True)
class PREvent:
    """Base fields shared by every PR-state event.

    Concrete subclasses (:class:`PROpened`, :class:`PRUpdated`, ...) carry
    the exact same structural fields today; the distinction is purely
    semantic and flows through :attr:`EventMeta.event_type`.  Keeping them
    as separate types preserves pattern-matching ergonomics while the base
    class removes field duplication.
    """

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
class PROpened(PREvent):
    """A pull request was opened."""


@dataclass(frozen=True)
class PRUpdated(PREvent):
    """A pull request was updated (new commits pushed, rebased, etc.)."""


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
    """A CI workflow run completed.

    ``failed_jobs`` is populated by the fetch layer (Step 2) — the raw
    ``workflow_run`` webhook does not include per-job results; they must
    be fetched via ``GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs``.
    """

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

    # TODO(Step 6): add `parse_slack_mention_event` / `parse_teams_mention_event`
    # parsers to accompany this type.

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
