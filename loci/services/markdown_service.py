"""Markdown, TXT, and pasted-text parsing with exact source-span sections."""

from __future__ import annotations

import re
from dataclasses import dataclass

from loci.models.schemas import ParsedDocument, SectionCandidate


HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
NUMBERED_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)[.)]?\s+(?P<title>[A-Z][^\n]{2,120})$")


@dataclass(frozen=True)
class Heading:
    title: str
    level: int
    start: int
    content_start: int


class MarkdownService:
    """Extract candidate sections without altering source text."""

    def parse(self, text: str, title: str | None = None, source_type: str = "markdown") -> ParsedDocument:
        headings = self._find_headings(text)
        if not headings:
            stripped_title = title or self._first_non_empty_line(text) or "Untitled"
            return ParsedDocument(
                raw_text=text,
                title=stripped_title,
                sections=[
                    SectionCandidate(
                        title=stripped_title,
                        level=1,
                        source_char_start=0,
                        source_char_end=len(text),
                        summary=self._fallback_summary(text),
                        confidence=0.8,
                    )
                ],
                metadata={"source_type": source_type, "parser": "heading-heuristic"},
            )

        sections: list[SectionCandidate] = []
        for index, heading in enumerate(headings):
            end = headings[index + 1].start if index + 1 < len(headings) else len(text)
            verbatim = text[heading.content_start:end].strip()
            sections.append(
                SectionCandidate(
                    title=heading.title,
                    level=heading.level,
                    source_char_start=heading.content_start,
                    source_char_end=end,
                    summary=self._fallback_summary(verbatim),
                    confidence=0.85,
                )
            )
        return ParsedDocument(
            raw_text=text,
            title=title or headings[0].title,
            sections=sections,
            metadata={"source_type": source_type, "parser": "heading-heuristic"},
        )

    def _find_headings(self, text: str) -> list[Heading]:
        headings: list[Heading] = []
        offset = 0
        for line in text.splitlines(keepends=True):
            clean = line.rstrip("\r\n")
            match = HEADING_RE.match(clean)
            if match:
                headings.append(
                    Heading(
                        title=match.group("title").strip(),
                        level=len(match.group("hashes")),
                        start=offset,
                        content_start=offset + len(line),
                    )
                )
            else:
                numbered = NUMBERED_RE.match(clean.strip())
                if numbered:
                    level = numbered.group("num").count(".") + 1
                    headings.append(
                        Heading(
                            title=clean.strip(),
                            level=level,
                            start=offset,
                            content_start=offset + len(line),
                        )
                    )
            offset += len(line)
        return headings

    def _first_non_empty_line(self, text: str) -> str | None:
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:120]
        return None

    def _fallback_summary(self, text: str, max_len: int = 240) -> str:
        compact = " ".join(text.strip().split())
        if not compact:
            return "No source text in this section."
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 1].rstrip() + "…"
