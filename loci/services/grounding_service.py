"""Lightweight grounding checks for AI-generated Loci artifacts."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from loci.models.schemas import Section


TOKEN_RE = re.compile(r"[A-Za-z0-9_+-]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def tokenize(text: str) -> list[str]:
    """Tokenize text into lower-cased lexical terms."""

    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 2]


class GroundingService:
    """Map generated claims back to source sections using lexical overlap.

    This is intentionally conservative: it does not prove semantic entailment,
    but it provides a transparent first-pass warning system and source links.
    """

    def check_artifact_grounding(self, content: str, candidate_sections: Iterable[Section]) -> tuple[list[dict], list[str], float]:
        sections = list(candidate_sections)
        warnings: list[str] = []
        references: list[dict] = []
        sentence_scores: list[float] = []

        section_tokens = {section.id: Counter(tokenize(section.verbatim_content)) for section in sections}
        sentences = [sentence.strip() for sentence in SENTENCE_RE.split(content) if sentence.strip()]
        if not sentences or not sections:
            return [], ["No source sections available for grounding."], 0.0

        for sentence in sentences:
            claim_tokens = set(tokenize(sentence))
            if not claim_tokens:
                continue
            best_section: Section | None = None
            best_score = 0.0
            for section in sections:
                source_terms = set(section_tokens[section.id])
                overlap = len(claim_tokens & source_terms)
                score = overlap / max(1, len(claim_tokens))
                if score > best_score:
                    best_score = score
                    best_section = section
            sentence_scores.append(best_score)
            if best_section is not None and best_score > 0:
                quote = self._best_quote(sentence, best_section.verbatim_content)
                references.append(
                    {
                        "document_id": best_section.document_id,
                        "section_id": best_section.id,
                        "quote": quote,
                        "confidence": min(1.0, best_score),
                        "note": f"Lexical grounding for: {sentence[:120]}",
                    }
                )
            if best_score < 0.2:
                warnings.append(f"Low grounding confidence for claim: {sentence[:160]}")

        confidence = sum(sentence_scores) / max(1, len(sentence_scores))
        return references, warnings, min(1.0, confidence)

    def validate_answer(self, answer: str, references: list[dict]) -> tuple[bool, list[str]]:
        """Validate that a generated answer carries at least one source citation."""

        warnings: list[str] = []
        if not references:
            warnings.append("Answer has no source grounding references.")
        if "outside knowledge" in answer.lower() and "outside knowledge" not in " ".join(str(r) for r in references).lower():
            warnings.append("Outside knowledge is mentioned; ensure it is explicitly labeled.")
        return not warnings, warnings

    def _best_quote(self, sentence: str, source: str, max_len: int = 220) -> str:
        terms = tokenize(sentence)
        source_lines = [line.strip() for line in source.splitlines() if line.strip()]
        if not source_lines:
            return source[:max_len]
        best_line = max(source_lines, key=lambda line: len(set(tokenize(line)) & set(terms)))
        return best_line[:max_len]
