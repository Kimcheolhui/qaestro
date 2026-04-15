"""Parsers that convert raw webhook JSON payloads into normalised event types.

Each parser is tolerant of missing fields, falling back to sensible defaults
so that incomplete or evolving webhook schemas don't cause hard failures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.core.contracts.events import (
    CICompleted,
    EventMeta,
    EventType,
    FileChange,
    PRCommented,
    PROpened,
    PRReviewed,
    PRUpdated,
)


def _get(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Safely traverse nested dicts, returning *default* on any missing key."""
    current: Any = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _parse_files(files: list[dict[str, Any]]) -> tuple[FileChange, ...]:
    """Convert a list of GitHub file-change dicts to FileChange tuples."""
    return tuple(
        FileChange(
            path=f.get("filename", ""),
            status=f.get("status", "modified"),
            additions=int(f.get("additions", 0)),
            deletions=int(f.get("deletions", 0)),
            patch=f.get("patch", ""),
        )
        for f in files
    )


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Pull-request events
# ---------------------------------------------------------------------------


def parse_github_pr_event(
    payload: dict[str, Any],
    action: str,
    correlation_id: str,
) -> PROpened | PRUpdated | None:
    """Parse a GitHub ``pull_request`` webhook payload.

    Returns :class:`PROpened` for ``"opened"`` actions and :class:`PRUpdated`
    for ``"synchronize"`` (and similar update actions).  Returns ``None`` for
    actions we don't handle.
    """
    pr: dict[str, Any] = payload.get("pull_request", {})
    repo: dict[str, Any] = payload.get("repository", {})

    if action == "opened":
        event_type = EventType.PR_OPENED
    elif action in {"synchronize", "edited", "reopened"}:
        event_type = EventType.PR_UPDATED
    else:
        return None

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        correlation_id=correlation_id,
        timestamp=_now(),
        source="github",
    )

    files_raw: list[dict[str, Any]] = payload.get("files", [])
    files_changed = _parse_files(files_raw)

    common_kwargs: dict[str, Any] = {
        "meta": meta,
        "repo_full_name": repo.get("full_name", ""),
        "pr_number": int(pr.get("number", 0)),
        "title": pr.get("title", ""),
        "body": pr.get("body", "") or "",
        "author": _get(pr, "user", "login"),
        "base_branch": _get(pr, "base", "ref"),
        "head_branch": _get(pr, "head", "ref"),
        "diff_url": pr.get("diff_url", ""),
        "files_changed": files_changed,
    }

    if event_type == EventType.PR_OPENED:
        return PROpened(**common_kwargs)
    return PRUpdated(**common_kwargs)


# ---------------------------------------------------------------------------
# CI events
# ---------------------------------------------------------------------------


def parse_github_ci_event(
    payload: dict[str, Any],
    correlation_id: str,
) -> CICompleted | None:
    """Parse a GitHub ``workflow_run`` webhook payload.

    Returns ``None`` when the workflow has not yet completed.
    """
    wf: dict[str, Any] = payload.get("workflow_run", {})
    repo: dict[str, Any] = payload.get("repository", {})

    conclusion = wf.get("conclusion", "")
    if not conclusion:
        return None

    # Determine associated PR number (if any)
    pr_numbers: list[dict[str, Any]] = wf.get("pull_requests", [])
    pr_number: int | None = int(pr_numbers[0]["number"]) if pr_numbers else None

    failed_jobs: list[str] = [j.get("name", "") for j in payload.get("failed_jobs", []) if j.get("name")]

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=EventType.CI_COMPLETED,
        correlation_id=correlation_id,
        timestamp=_now(),
        source="github",
    )

    return CICompleted(
        meta=meta,
        repo_full_name=repo.get("full_name", ""),
        pr_number=pr_number,
        commit_sha=_get(wf, "head_sha"),
        workflow_name=wf.get("name", ""),
        conclusion=conclusion,
        run_url=wf.get("html_url", ""),
        failed_jobs=tuple(failed_jobs),
        logs_url=wf.get("logs_url", ""),
    )


# ---------------------------------------------------------------------------
# PR review events
# ---------------------------------------------------------------------------


def parse_github_pr_review_event(
    payload: dict[str, Any],
    correlation_id: str,
) -> PRReviewed | None:
    """Parse a GitHub ``pull_request_review`` webhook payload."""
    review: dict[str, Any] = payload.get("review", {})
    pr: dict[str, Any] = payload.get("pull_request", {})
    repo: dict[str, Any] = payload.get("repository", {})

    state_raw = review.get("state", "")
    if not state_raw:
        return None

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=EventType.PR_REVIEWED,
        correlation_id=correlation_id,
        timestamp=_now(),
        source="github",
    )

    return PRReviewed(
        meta=meta,
        repo_full_name=repo.get("full_name", ""),
        pr_number=int(pr.get("number", 0)),
        reviewer=_get(review, "user", "login"),
        state=state_raw.lower(),
        body=review.get("body", "") or "",
    )


# ---------------------------------------------------------------------------
# Comment events
# ---------------------------------------------------------------------------


def parse_github_comment_event(
    payload: dict[str, Any],
    correlation_id: str,
) -> PRCommented | None:
    """Parse a GitHub ``issue_comment`` or ``pull_request_review_comment`` webhook payload."""
    comment: dict[str, Any] = payload.get("comment", {})
    repo: dict[str, Any] = payload.get("repository", {})

    # Determine PR number — either from pull_request or issue
    pr_number = 0
    if "pull_request" in payload:
        pr_number = int(payload["pull_request"].get("number", 0))
    elif "issue" in payload:
        pr_number = int(payload["issue"].get("number", 0))

    if not comment:
        return None

    is_review_comment = "pull_request_review_id" in comment

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=EventType.PR_COMMENTED,
        correlation_id=correlation_id,
        timestamp=_now(),
        source="github",
    )

    return PRCommented(
        meta=meta,
        repo_full_name=repo.get("full_name", ""),
        pr_number=pr_number,
        comment_id=int(comment.get("id", 0)),
        author=_get(comment, "user", "login"),
        body=comment.get("body", "") or "",
        is_review_comment=is_review_comment,
        path=comment.get("path", "") or "",
        line=comment.get("line"),
    )
