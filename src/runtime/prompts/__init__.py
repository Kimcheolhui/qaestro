"""Central Agent Runtime prompt catalog loader."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PromptCatalogError(RuntimeError):
    """Raised when a centrally managed prompt cannot be loaded or rendered."""


class PromptId(StrEnum):
    """Stable prompt identifiers used by Agent Runtime stages."""

    PR_WORKFLOW_TRIAGE = "pr-workflow-triage"
    VALIDATION_API_CONTRACT_PROBE_SELECTION = "validation-api-contract-probe-selection"


@dataclass(frozen=True)
class PromptTemplate:
    """Loaded prompt template text and source path for auditability."""

    identifier: PromptId
    path: str
    text: str


_PROMPT_DIR = Path(__file__).with_name("catalog")
_PROMPT_FILES = {
    PromptId.PR_WORKFLOW_TRIAGE: "pr-workflow-triage.md",
    PromptId.VALIDATION_API_CONTRACT_PROBE_SELECTION: "validation-api-contract-probe-selection.md",
}


def load_prompt(identifier: PromptId | str) -> PromptTemplate:
    """Load a markdown prompt template by stable identifier."""
    prompt_id = _normalize_prompt_id(identifier)
    path = _PROMPT_DIR / _PROMPT_FILES[prompt_id]
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptCatalogError(f"prompt file not found for {prompt_id.value}: {path}") from exc
    if not text:
        raise PromptCatalogError(f"prompt file is empty for {prompt_id.value}: {path}")
    return PromptTemplate(identifier=prompt_id, path=str(path), text=text)


def render_prompt(identifier: PromptId | str, **variables: object) -> str:
    """Load and render a prompt template with explicit runtime variables."""
    template = load_prompt(identifier)
    try:
        return template.text.format(**{key: str(value) for key, value in variables.items()})
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise PromptCatalogError(f"missing template variable {missing!r} for {template.identifier.value}") from exc


def _normalize_prompt_id(identifier: PromptId | str) -> PromptId:
    try:
        return identifier if isinstance(identifier, PromptId) else PromptId(identifier)
    except ValueError as exc:
        raise PromptCatalogError(f"unknown prompt id: {identifier!r}") from exc
