"""Tests for live-provider PR review E2E smoke wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.smoke.llm_pr_review_e2e import LLMPRE2ESmokeResult, SmokeGitHubAuth, run_llm_pr_review_e2e_smoke

from src.adapters.connectors.github import FakeResponse, FakeTransport, GitHubAppAuth, GitHubClient
from src.runtime.agent.azure_openai import AzureOpenAIClientResponse
from src.shared.config import AgentRuntimeConfig, AgentRuntimeProvider, AppConfig, load_config


class StaticTokenAuth:
    def installation_token(self) -> str:
        return "test-token"


def _json_response(payload: object) -> FakeResponse:
    return FakeResponse(body=json.dumps(payload).encode("utf-8"))


def test_llm_pr_review_e2e_smoke_module_exists() -> None:
    assert LLMPRE2ESmokeResult is not None
    assert callable(run_llm_pr_review_e2e_smoke)


@pytest.mark.integration
def test_llm_pr_review_e2e_smoke_requires_explicit_opt_in() -> None:
    result = run_llm_pr_review_e2e_smoke(
        config=load_config(),
        repo_full_name="Kimcheolhui/qaestro-test",
        pr_number=4,
        opt_in_live_smoke=False,
    )

    assert result.status == "not_requested"
    assert result.ok is False


def test_llm_pr_review_e2e_smoke_rejects_disabled_provider() -> None:
    result = run_llm_pr_review_e2e_smoke(
        config=AppConfig(),
        repo_full_name="Kimcheolhui/qaestro-test",
        pr_number=4,
        opt_in_live_smoke=True,
    )

    assert result.status == "failed"
    assert "azure-openai" in result.error
    assert result.provider_request_count == 0


def test_llm_pr_review_e2e_smoke_runs_live_provider_workflow_and_posts_outputs() -> None:
    transport = FakeTransport()
    pr_view_payload = {
        "number": 4,
        "title": "feat(api): add review target",
        "body": "Adds the API review target and updates tests.",
        "state": "open",
        "head": {"sha": "head123", "ref": "feat/api"},
        "base": {"ref": "main"},
        "user": {"login": "Kimcheolhui"},
        "draft": False,
        "html_url": "https://github.com/Kimcheolhui/qaestro-test/pull/4",
    }
    transport.enqueue(_json_response(pr_view_payload))
    transport.enqueue(
        _json_response(
            [
                {
                    "filename": "src/api.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 1,
                    "changes": 6,
                    "patch": "@@ -1,1 +3,2 @@\n+def api():\n+    return True",
                }
            ]
        )
    )
    transport.enqueue(
        _json_response(
            {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "Tests",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/Kimcheolhui/qaestro-test/actions/runs/1",
                        "head_sha": "head123",
                    }
                ],
            }
        )
    )
    transport.enqueue(_json_response(pr_view_payload))
    transport.enqueue(
        _json_response(
            [
                {
                    "filename": "src/api.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 1,
                    "changes": 6,
                    "patch": "@@ -1,1 +3,2 @@\n+def api():\n+    return True",
                }
            ]
        )
    )
    transport.enqueue(
        FakeResponse(body=b"diff --git a/src/api.py b/src/api.py\n@@ -1,1 +1,2 @@\n+def api():\n+    return True")
    )
    transport.enqueue(_json_response({"number": 4, "head": {"sha": "head123"}}))
    transport.enqueue(_json_response([]))
    transport.enqueue(_json_response([]))
    transport.enqueue(_json_response(pr_view_payload))
    transport.enqueue(
        _json_response(
            {
                "id": 100,
                "html_url": "https://github.com/Kimcheolhui/qaestro-test/pull/4#issuecomment-100",
                "body": "summary",
            }
        )
    )
    transport.enqueue(
        _json_response(
            {
                "id": 200,
                "html_url": "https://github.com/Kimcheolhui/qaestro-test/pull/4#pullrequestreview-200",
                "state": "COMMENTED",
                "body": "review",
                "commit_id": "head123",
            }
        )
    )
    client = GitHubClient(auth=cast(GitHubAppAuth, StaticTokenAuth()), transport=transport)
    cfg = AppConfig(
        agent_runtime=AgentRuntimeConfig(
            provider=AgentRuntimeProvider.AZURE_OPENAI,
            deployment="smoke-deployment",
            endpoint="https://example.openai.azure.com/openai/v1",
            api_version="2024-10-21",
            credential_env_var="AZURE_OPENAI_API_KEY",
            supports_tool_calling=True,
            supports_structured_output=True,
            context_window_tokens=128000,
        )
    )

    class RecordingLiveClient:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        def complete(self, request: dict[str, object]) -> AzureOpenAIClientResponse:
            self.requests.append(request)
            return AzureOpenAIClientResponse(output_text="qaestro-live-e2e-ok")

    live_client = RecordingLiveClient()

    result = run_llm_pr_review_e2e_smoke(
        config=cfg,
        repo_full_name="Kimcheolhui/qaestro-test",
        pr_number=4,
        correlation_id="corr-live-e2e",
        github_client=client,
        azure_openai_client=live_client,
        environ={"AZURE_OPENAI_API_KEY": "secret"},
        opt_in_live_smoke=True,
    )

    assert result.ok is True
    assert result.status == "succeeded"
    assert result.provider_output_marker == "qaestro-live-provider-output-present"
    assert result.provider_request_count == 1
    assert result.comment_url
    assert result.review_url
    assert result.head_sha == "head123"
    assert result.inline_comment_submitted is True
    assert len(live_client.requests) == 1
    prompt = str(live_client.requests[0]["prompt"])
    assert "PR description" in prompt
    assert "Changed files" in prompt
    assert "CI/check feedback" in prompt
    assert "Return a concise review" in prompt

    post_comment_calls = [
        call for call in transport.calls if call.method == "POST" and call.url.endswith("/issues/4/comments")
    ]
    assert len(post_comment_calls) == 1
    summary_body = json.loads((post_comment_calls[0].body or b"{}").decode("utf-8"))["body"]
    assert "LLM PR Review" in summary_body
    assert "qaestro-live-e2e-ok" in summary_body

    post_review_calls = [
        call for call in transport.calls if call.method == "POST" and call.url.endswith("/pulls/4/reviews")
    ]
    assert len(post_review_calls) == 1
    review_body = json.loads((post_review_calls[0].body or b"{}").decode("utf-8"))["body"]
    assert "LLM PR Review" in review_body
    assert "qaestro-live-e2e-ok" in review_body
    assert "qaestro-live-provider-output-present" in review_body
    assert "Correlation ID: `corr-live-e2e`" in review_body


def test_llm_pr_review_e2e_smoke_script_exists() -> None:
    script = Path("scripts/llm_pr_review_e2e_smoke.py")

    assert script.exists()
    assert "sys.path.insert" in script.read_text(encoding="utf-8")


def test_smoke_github_auth_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="token"):
        SmokeGitHubAuth("")

    assert SmokeGitHubAuth("token").installation_token() == "token"
