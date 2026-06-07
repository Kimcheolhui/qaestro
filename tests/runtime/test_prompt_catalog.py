"""Tests for central Agent Runtime prompt catalog loading."""

from __future__ import annotations

import pytest

from src.runtime.prompts import PromptCatalogError, PromptId, load_prompt, render_prompt


def test_prompt_catalog_loads_markdown_prompt_body_without_frontmatter() -> None:
    prompt = load_prompt(PromptId.PR_WORKFLOW_TRIAGE)

    assert prompt.identifier is PromptId.PR_WORKFLOW_TRIAGE
    assert prompt.path.endswith("pr-workflow-triage.md")
    assert prompt.text.startswith("You are qaestro's PR workflow triage layer.")
    assert "Do not classify PRs from path taxonomies alone" in prompt.text
    assert "---" not in prompt.text.splitlines()[0]


def test_prompt_catalog_renders_runtime_variables_explicitly() -> None:
    prompt_text = render_prompt(
        PromptId.VALIDATION_API_CONTRACT_PROBE_SELECTION,
        action_type="verify_api_contract",
        target="GET /health",
        description="Check health endpoint",
        rationale="API contract changed",
    )

    assert "Action type: verify_api_contract" in prompt_text
    assert "Target: GET /health" in prompt_text
    assert "Description: Check health endpoint" in prompt_text
    assert "Rationale: API contract changed" in prompt_text


def test_validation_prompt_contains_secret_safety_instruction() -> None:
    prompt_text = render_prompt(
        PromptId.VALIDATION_API_CONTRACT_PROBE_SELECTION,
        action_type="verify_api_contract",
        target="GET /health",
        description="Check health endpoint",
        rationale="API contract changed",
    )

    assert "Do not include secrets, tokens, credentials, private keys, raw provider errors" in prompt_text
    assert "[REDACTED]" in prompt_text


def test_prompt_catalog_rejects_missing_template_variables() -> None:
    with pytest.raises(PromptCatalogError, match="missing template variable"):
        render_prompt(
            PromptId.VALIDATION_API_CONTRACT_PROBE_SELECTION,
            action_type="verify_api_contract",
            target="GET /health",
            description="Check health endpoint",
        )
