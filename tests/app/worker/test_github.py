"""Tests for GitHub worker comment posting adapter."""

from __future__ import annotations

import pytest

from src.adapters.renderers import PRCommentPayload
from src.app.worker import GitHubCommentPoster


class RecordingGitHubClient:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str, int, str]] = []

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> None:
        self.comments.append((owner, repo, number, body))


def test_github_comment_poster_posts_pr_comment_payload() -> None:
    client = RecordingGitHubClient()
    poster = GitHubCommentPoster(client)
    payload = PRCommentPayload(repo_full_name="Kimcheolhui/qaestro", pr_number=32, body="hello")

    poster.post_comment(payload)

    assert client.comments == [("Kimcheolhui", "qaestro", 32, "hello")]


def test_github_comment_poster_rejects_invalid_repo_full_name() -> None:
    client = RecordingGitHubClient()
    poster = GitHubCommentPoster(client)
    payload = PRCommentPayload(repo_full_name="invalid", pr_number=32, body="hello")

    with pytest.raises(ValueError, match="repo_full_name"):
        poster.post_comment(payload)
