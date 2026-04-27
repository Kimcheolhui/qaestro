"""Knowledge query models and in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeEntry:
    """A QA knowledge item that can influence strategy selection.

    ``topics`` are coarse matching tags such as impact surfaces, product areas,
    or feature names. They are intentionally not tied to a single taxonomy.
    """

    key: str
    summary: str
    topics: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    checklist_items: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeQuery:
    """Provider-neutral query for matching QA knowledge.

    ``search_terms`` are free-text tokens extracted from PR title, changed files,
    and impact output. A future adapter may translate them to BM25/vector search.
    """

    repo_full_name: str
    topics: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()


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
        """Return entries matching repo scope plus optional topics/text terms."""
        query_topics = {topic.lower() for topic in query.topics}
        query_terms = {term.lower() for term in query.search_terms if term.strip()}
        matches: list[KnowledgeEntry] = []
        for entry in self._entries:
            if entry.repos and query.repo_full_name not in entry.repos:
                continue
            entry_topics = {topic.lower() for topic in entry.topics}
            topic_match = not query_topics or bool(query_topics & entry_topics)
            term_match = not query_terms or _entry_matches_terms(entry, query_terms)
            if topic_match and term_match:
                matches.append(entry)
        return tuple(sorted(matches, key=lambda entry: entry.key))


def _entry_matches_terms(entry: KnowledgeEntry, terms: set[str]) -> bool:
    """Search the in-memory entry fields with simple substring matching."""
    haystack = " ".join(
        (
            entry.key,
            entry.summary,
            " ".join(entry.topics),
            " ".join(entry.checklist_items),
        )
    ).lower()
    return any(term in haystack for term in terms)
