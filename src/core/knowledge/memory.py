"""Knowledge query models and in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeEntry:
    """A QA knowledge item that can influence strategy selection."""

    key: str
    summary: str
    domains: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    checklist_items: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeQuery:
    """Provider-neutral query for matching QA knowledge."""

    repo_full_name: str
    domains: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


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
        query_domains = {domain.lower() for domain in query.domains}
        query_terms = {term.lower() for term in query.terms if term.strip()}
        matches: list[KnowledgeEntry] = []
        for entry in self._entries:
            if entry.repos and query.repo_full_name not in entry.repos:
                continue
            entry_domains = {domain.lower() for domain in entry.domains}
            domain_match = not query_domains or bool(query_domains & entry_domains)
            term_match = not query_terms or _entry_matches_terms(entry, query_terms)
            if domain_match and term_match:
                matches.append(entry)
        return tuple(sorted(matches, key=lambda entry: entry.key))


def _entry_matches_terms(entry: KnowledgeEntry, terms: set[str]) -> bool:
    haystack = " ".join(
        (
            entry.key,
            entry.summary,
            " ".join(entry.domains),
            " ".join(entry.checklist_items),
        )
    ).lower()
    return any(term in haystack for term in terms)
