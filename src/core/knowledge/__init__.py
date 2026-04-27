"""Knowledge Store port — query model and in-memory mock."""

from __future__ import annotations

from .memory import InMemoryKnowledgeBase, KnowledgeBase, KnowledgeEntry, KnowledgeQuery

__all__ = [
    "InMemoryKnowledgeBase",
    "KnowledgeBase",
    "KnowledgeEntry",
    "KnowledgeQuery",
]
