"""Embedding generation with OpenAI and deterministic offline fallback."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

from loci.services.openai_service import OpenAIService
from loci.services.storage_service import StorageService


class EmbeddingService:
    """Create and persist vectors for searchable knowledge-base objects."""

    def __init__(self, storage: StorageService, openai_service: OpenAIService | None = None) -> None:
        self.storage = storage
        self.openai = openai_service or OpenAIService()

    def embed_text(self, text: str) -> tuple[list[float], str]:
        if self.openai.enabled and self.openai.client is not None:
            try:
                response = self.openai.client.embeddings.create(model="text-embedding-3-small", input=text[:8000])
                return list(response.data[0].embedding), "text-embedding-3-small"
            except Exception:
                pass
        return self._fallback_vector(text), "fallback-hash-vector"

    def index_section(self, section_id: str, text: str) -> None:
        vector, model = self.embed_text(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.storage.save_embedding("section", section_id, digest, model, vector)

    def _fallback_vector(self, text: str, dimensions: int = 64) -> list[float]:
        vector = [0.0] * dimensions
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        for token in tokens:
            idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % dimensions
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    @staticmethod
    def cosine(left: Iterable[float], right: Iterable[float]) -> float:
        l = list(left)
        r = list(right)
        if not l or not r or len(l) != len(r):
            return 0.0
        dot = sum(a * b for a, b in zip(l, r, strict=True))
        nl = math.sqrt(sum(a * a for a in l)) or 1.0
        nr = math.sqrt(sum(b * b for b in r)) or 1.0
        return dot / (nl * nr)
