"""Parsers that convert raw webhook JSON payloads into normalised event types.

Each parser is tolerant of missing fields, falling back to sensible defaults
so that incomplete or evolving webhook schemas don't cause hard failures.

These parsers intentionally produce **lightweight** events:

* ``FileChange`` carries only per-file metadata (path, status, line counts).
  Actual diff text and file contents are NOT attached — they are fetched
  on-demand by the Step 2 fetch layer.
* ``CICompleted.failed_jobs`` is populated from a synthetic ``failed_jobs``
  key if present (used by test fixtures).  In production the real
  ``workflow_run`` webhook has no such field; the fetch layer must
  enrich the event from ``GET /repos/.../actions/runs/{id}/jobs``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .events import (
    CICompleted,
    EventMeta,
    EventSource,
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
    """Convert a list of GitHub file-change dicts to FileChange tuples.

    Note: real ``pull_request`` webhook payloads don't include this array —
    it must be fetched separately. Parsers accept it here so test fixtures
    and the future fetch layer can feed pre-enriched payloads through the
    same code path.
    """
    return tuple(
        FileChange(
            path=f.get("filename", ""),
            status=f.get("status", "modified"),
            additions=int(f.get("additions", 0)),
            deletions=int(f.get("deletions", 0)),
            previous_filename=f.get("previous_filename", "") or "",
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
        source=EventSource.GITHUB,
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
        "head_sha": _get(pr, "head", "sha"),
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
    pr_number: int | None = int(pr_numbers[0].get("number", 0)) if pr_numbers else None

    failed_jobs: list[str] = [j.get("name", "") for j in payload.get("failed_jobs", []) if j.get("name")]

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=EventType.CI_COMPLETED,
        correlation_id=correlation_id,
        timestamp=_now(),
        source=EventSource.GITHUB,
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
        run_id=int(wf["id"]) if wf.get("id") is not None else None,
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
        source=EventSource.GITHUB,
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

    # Determine PR number — distinguish between PR comments and issue comments.
    # GitHub's ``issue_comment`` webhook fires for BOTH issues and PRs.  We only
    # want to emit ``PRCommented`` for actual PR conversations; plain-issue
    # comments are out of scope for qaestro and must be dropped.
    #
    # Disambiguation rules:
    # * ``payload["pull_request"]`` present  → PR review-comment payload
    # * ``payload["issue"]["pull_request"]`` present → issue_comment on a PR
    #   (GitHub injects this nested object when the issue is a PR)
    # * otherwise the comment belongs to a plain issue — return ``None``
    pr_number = 0
    if "pull_request" in payload:
        pr_number = int(payload["pull_request"].get("number", 0))
    elif "issue" in payload:
        issue: dict[str, Any] = payload.get("issue", {})
        if not issue.get("pull_request"):
            return None
        pr_number = int(issue.get("number", 0))
    else:
        return None

    if not comment:
        return None

    is_review_comment = "pull_request_review_id" in comment

    meta = EventMeta(
        event_id=str(uuid.uuid4()),
        event_type=EventType.PR_COMMENTED,
        correlation_id=correlation_id,
        timestamp=_now(),
        source=EventSource.GITHUB,
    )

    raw_line = comment.get("line")
    line: int | None = int(raw_line) if raw_line is not None else None

    return PRCommented(
        meta=meta,
        repo_full_name=repo.get("full_name", ""),
        pr_number=pr_number,
        comment_id=int(comment.get("id", 0)),
        author=_get(comment, "user", "login"),
        body=comment.get("body", "") or "",
        is_review_comment=is_review_comment,
        path=comment.get("path", "") or "",
        line=line,
    )
