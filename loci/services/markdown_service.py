"""Markdown, TXT, and pasted-text parsing with exact source-span sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from loci.models.schemas import EquationCandidate, FigureCandidate, ParsedDocument, SectionCandidate


HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
NUMBERED_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)[.)]?\s+(?P<title>[A-Z][^\n]{2,120})$")
IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"(?P<title>[^\"]*)\")?\)")
DISPLAY_MATH_RE = re.compile(r"\$\$(?P<dollar>.*?)\$\$|\\\[(?P<bracket>.*?)\\\]", re.DOTALL)
EQUATION_LINE_RE = re.compile(r"^(?P<expr>(?=.*[=∑∫√≤≥≈±])(?=.*[+\-*/^=()]).{3,180})$")


@dataclass(frozen=True)
class Heading:
    title: str
    level: int
    start: int
    content_start: int


class MarkdownService:
    """Extract candidate sections without altering source text."""

    def parse(
        self,
        text: str,
        title: str | None = None,
        source_type: str = "markdown",
        base_dir: str | Path | None = None,
    ) -> ParsedDocument:
        headings = self._find_headings(text)
        figures = self._find_figures(text, base_dir)
        equations = self._find_equations(text)
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
                figures=figures,
                equations=equations,
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
            figures=figures,
            equations=equations,
            metadata={"source_type": source_type, "parser": "heading-heuristic"},
        )

    def _find_figures(self, text: str, base_dir: str | Path | None) -> list[FigureCandidate]:
        figures: list[FigureCandidate] = []
        base_path = Path(base_dir) if base_dir is not None else None
        for index, match in enumerate(IMAGE_RE.finditer(text)):
            target = match.group("target")
            resolved = target
            if base_path is not None and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                resolved = str((base_path / target).expanduser().resolve())
            figures.append(
                FigureCandidate(
                    crop_path=resolved,
                    caption=match.group("title") or match.group("alt") or None,
                    confidence=0.9,
                    metadata={
                        "source_char_start": match.start(),
                        "source_char_end": match.end(),
                        "order_index": index,
                        "markdown_token": match.group(0),
                        "alt_text": match.group("alt"),
                        "original_path": target,
                        "source": "markdown",
                    },
                )
            )
        return figures

    def _find_equations(self, text: str) -> list[EquationCandidate]:
        equations: list[EquationCandidate] = []
        consumed: list[tuple[int, int]] = []
        for index, match in enumerate(DISPLAY_MATH_RE.finditer(text)):
            expression = (match.group("dollar") or match.group("bracket") or "").strip()
            if not expression:
                continue
            consumed.append((match.start(), match.end()))
            equations.append(
                EquationCandidate(
                    source_text=match.group(0),
                    mathjax=expression,
                    confidence=0.9,
                    metadata={
                        "source_char_start": match.start(),
                        "source_char_end": match.end(),
                        "order_index": index,
                        "source": "markdown",
                        "delimiter": "$$" if match.group("dollar") is not None else r"\[\]",
                    },
                )
            )
        offset = 0
        for line in text.splitlines(keepends=True):
            clean = line.strip()
            span = (offset, offset + len(line))
            offset += len(line)
            if not clean or any(start <= span[0] < end for start, end in consumed):
                continue
            match = EQUATION_LINE_RE.match(clean)
            if not match:
                continue
            equations.append(
                EquationCandidate(
                    source_text=clean,
                    mathjax=self._normalize_mathjax(clean),
                    confidence=0.65,
                    metadata={
                        "source_char_start": span[0] + line.index(clean),
                        "source_char_end": span[0] + line.index(clean) + len(clean),
                        "order_index": len(equations),
                        "source": "markdown",
                        "delimiter": "line",
                    },
                )
            )
        return equations

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

    @staticmethod
    def _normalize_mathjax(expression: str) -> str:
        return (
            expression.replace("≤", r"\le ")
            .replace("≥", r"\ge ")
            .replace("≈", r"\approx ")
            .replace("±", r"\pm ")
        )
