"""Knowledge query models and in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeEntry:
    """A QA knowledge item that can influence strategy selection."""

    key: str
    summary: str
    repos: tuple[str, ...] = ()
    checklist_items: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeQuery:
    """Provider-neutral text query for matching QA knowledge.

    Step 3 builds this text from PR title and analyzer output. Later adapters can
    replace the simple text match with BM25/vector search without changing the
    strategy engine contract.
    """

    repo_full_name: str
    query_text: str = ""


class KnowledgeBase(Protocol):
    """Read-side port used by the Strategy Engine."""

    def search(self, query: KnowledgeQuery) -> tuple[KnowledgeEntry, ...]: ...


class InMemoryKnowledgeBase:
    """Deterministic in-memory knowledge adapter for Step 3.

    This is the P0 mock implementation. Actual markdown/vector/database backing
    stores belong in ``adapters/knowledge`` in later milestones.
    """

    def __init__(self, entries: tuple[KnowledgeEntry, ...] = ()) -> None:
        self._entries = entries

    def search(self, query: KnowledgeQuery) -> tuple[KnowledgeEntry, ...]:
        """Return entries matching repo scope and optional free-text query."""
        query_terms = _tokens(query.query_text)
        matches: list[KnowledgeEntry] = []
        for entry in self._entries:
            if entry.repos and query.repo_full_name not in entry.repos:
                continue
            if not query_terms or _entry_matches_terms(entry, query_terms):
                matches.append(entry)
        return tuple(sorted(matches, key=lambda entry: entry.key))


def _entry_matches_terms(entry: KnowledgeEntry, terms: set[str]) -> bool:
    """Search the in-memory entry fields with simple token matching."""
    haystack = " ".join(
        (
            entry.key,
            entry.summary,
            " ".join(entry.checklist_items),
        )
    )
    entry_terms = _tokens(haystack)
    return bool(terms & entry_terms) or any(term in haystack.lower() for term in terms)


def _tokens(text: str) -> set[str]:
    """Tokenize query text without committing to a final search backend."""
    return {token.strip(".,:;()[]{}#'\"").lower() for token in text.split() if len(token.strip(".,:;()[]{}#'\"")) >= 3}
