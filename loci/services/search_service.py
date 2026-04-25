"""Lexical and embedding-assisted section search."""

from __future__ import annotations

import math
import re
from collections import Counter

from loci.models.schemas import Scope, SearchResult
from loci.services.embedding_service import EmbeddingService
from loci.services.storage_service import StorageService


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SearchService:
    """Search sections while respecting document/section scope filters."""

    def __init__(self, storage: StorageService, embeddings: EmbeddingService | None = None) -> None:
        self.storage = storage
        self.embeddings = embeddings or EmbeddingService(storage)

    def search_sections(self, query: str, scope: Scope | None = None, limit: int = 8) -> list[SearchResult]:
        scope = scope or Scope()
        sections = self._candidate_sections(scope)
        if not sections:
            return []

        query_tokens = Counter(_tokens(query))
        query_vector = self.embeddings.embed_text(query)
        stored_embeddings = {
            item["owner_id"]: item["vector"]
            for item in self.storage.list_embeddings("section")
            if item.get("embedding_type") in {None, "content", "summary", "verbatim"}
        }

        results: list[SearchResult] = []
        for section in sections:
            haystack = f"{section.title}\n{section.ai_summary}\n{section.verbatim_content}"
            hay_tokens = Counter(_tokens(haystack))
            lexical = sum(min(count, hay_tokens[token]) for token, count in query_tokens.items())
            title_boost = 2.0 if any(token in _tokens(section.title) for token in query_tokens) else 0.0
            vector_score = _cosine(query_vector, stored_embeddings.get(section.id, []))
            score = float(lexical) + title_boost + vector_score
            if not query_tokens:
                score = max(score, 0.05)
            if score <= 0:
                continue
            snippet = self._snippet(section.verbatim_content, list(query_tokens))
            results.append(
                SearchResult(
                    section_id=section.id,
                    document_id=section.document_id,
                    title=section.title,
                    score=score,
                    snippet=snippet,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def _candidate_sections(self, scope: Scope):
        if scope.section_ids:
            return [section for sid in scope.section_ids if (section := self.storage.get_section(sid))]
        if scope.section_id:
            section = self.storage.get_section(scope.section_id)
            if not section:
                return []
            siblings = self.storage.list_sections(section.document_id)
            return [item for item in siblings if item.id == section.id or item.parent_id == section.id]
        if scope.document_id:
            return self.storage.list_sections(scope.document_id)
        return self.storage.list_sections()

    @staticmethod
    def _snippet(text: str, query_tokens: list[str]) -> str:
        lower = text.lower()
        index = min((lower.find(token) for token in query_tokens if lower.find(token) >= 0), default=0)
        start = max(0, index - 80)
        end = min(len(text), index + 220)
        snippet = text[start:end].strip()
        if start:
            snippet = "…" + snippet
        if end < len(text):
            snippet += "…"
        return snippet
