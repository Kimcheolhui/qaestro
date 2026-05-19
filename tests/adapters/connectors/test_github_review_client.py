"""Tests for official GitHub review REST endpoints."""

from __future__ import annotations

import json
from typing import cast

import pytest

from src.adapters.connectors.github import GitHubAppAuth, GitHubClient, ReviewCommentInput
from src.adapters.connectors.github.transport import FakeResponse, FakeTransport

OWNER = "octocat"
REPO = "hello-world"
PR_NUM = 42


class StaticTokenAuth:
    def installation_token(self) -> str:
        return "test-token"


@pytest.fixture
def client() -> tuple[GitHubClient, FakeTransport]:
    transport = FakeTransport()
    return GitHubClient(auth=cast(GitHubAppAuth, StaticTokenAuth()), transport=transport), transport


def test_create_pull_request_review_posts_body_head_and_inline_comments(
    client: tuple[GitHubClient, FakeTransport],
) -> None:
    github, transport = client
    transport.enqueue(
        FakeResponse(
            status=201,
            body=json.dumps(
                {
                    "id": 777,
                    "html_url": "https://github.com/octocat/hello-world/pull/42#pullrequestreview-777",
                    "state": "COMMENTED",
                    "body": "review body",
                    "commit_id": "abc123",
                }
            ).encode(),
        )
    )

    result = github.create_pull_request_review(
        OWNER,
        REPO,
        PR_NUM,
        body="review body",
        commit_id="abc123",
        event="COMMENT",
        comments=(
            ReviewCommentInput(path="src/app.py", body="line comment", line=12),
            ReviewCommentInput(
                path="src/range.py",
                body="range comment",
                start_line=10,
                line=12,
                side="RIGHT",
                start_side="RIGHT",
            ),
        ),
    )

    assert result.id == 777
    assert result.html_url.endswith("pullrequestreview-777")
    assert result.commit_id == "abc123"
    api_call = next(call for call in transport.calls if "/pulls/42/reviews" in call.url)
    assert api_call.body is not None
    assert api_call.method == "POST"
    assert json.loads(api_call.body) == {
        "body": "review body",
        "commit_id": "abc123",
        "event": "COMMENT",
        "comments": [
            {"path": "src/app.py", "body": "line comment", "line": 12, "side": "RIGHT"},
            {
                "path": "src/range.py",
                "body": "range comment",
                "line": 12,
                "side": "RIGHT",
                "start_line": 10,
                "start_side": "RIGHT",
            },
        ],
    }


def test_list_pull_request_reviews_returns_typed_reviews(client: tuple[GitHubClient, FakeTransport]) -> None:
    github, transport = client
    transport.enqueue(
        FakeResponse(
            body=json.dumps(
                [
                    {
                        "id": 777,
                        "html_url": "https://github.com/octocat/hello-world/pull/42#pullrequestreview-777",
                        "state": "COMMENTED",
                        "body": "review body",
                        "commit_id": "abc123",
                    }
                ]
            ).encode(),
        )
    )

    reviews = github.list_pull_request_reviews(OWNER, REPO, PR_NUM)

    assert len(reviews) == 1
    assert reviews[0].id == 777
    assert reviews[0].body == "review body"
    assert reviews[0].commit_id == "abc123"
    api_call = next(call for call in transport.calls if "/pulls/42/reviews" in call.url)
    assert api_call.method == "GET"


def test_create_pull_request_review_rejects_empty_body_and_comments(client: tuple[GitHubClient, FakeTransport]) -> None:
    github, _transport = client

    with pytest.raises(ValueError, match="review body or comments"):
        github.create_pull_request_review(OWNER, REPO, PR_NUM, body="", commit_id="abc123", comments=())


def test_create_pull_request_review_rejects_unmapped_comment(client: tuple[GitHubClient, FakeTransport]) -> None:
    github, _transport = client

    with pytest.raises(ValueError, match="review comment line"):
        github.create_pull_request_review(
            OWNER,
            REPO,
            PR_NUM,
            body="review body",
            commit_id="abc123",
            comments=(ReviewCommentInput(path="src/app.py", body="missing line"),),
        )
