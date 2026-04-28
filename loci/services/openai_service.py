"""OpenAI integration with deterministic offline fallbacks.

The service is intentionally usable without credentials so the desktop app and
tests remain runnable offline. When ``OPENAI_API_KEY`` is present, this module
can be extended to make richer structured-output calls while preserving the
same return schemas.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from loci.models.schemas import AIArtifact, Section, SectionCandidate, iso_now, new_id
from loci.services.grounding_service import GroundingService


class OpenAIService:
    """Generation/extraction facade for Loci."""

    prompt_version = "1.0"

    def __init__(self, prompts_dir: str | Path | None = None, model: str = "gpt-4o-mini") -> None:
        load_dotenv()
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = model if self.api_key else "fallback-local"
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).resolve().parents[1] / "prompts"
        self.grounding = GroundingService()
        self.client = None
        self.enabled = False
        if self.api_key:
            try:
                from openai import OpenAI

                self.client = OpenAI(api_key=self.api_key)
                self.enabled = True
            except Exception:
                self.client = None
                self.enabled = False

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def prompt(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def extract_sections(self, raw_text: str, metadata: dict[str, Any] | None = None) -> list[SectionCandidate]:
        """Return source-span section candidates.

        The fallback never invents content. It only identifies heading spans and
        returns indexes into ``raw_text``.
        """

        lines = raw_text.splitlines(keepends=True)
        headings: list[tuple[int, int, str, int]] = []
        offset = 0
        for line in lines:
            stripped = line.strip()
            level = 0
            title = ""
            if stripped.startswith("#"):
                marks = len(stripped) - len(stripped.lstrip("#"))
                if 1 <= marks <= 6 and stripped[marks:].strip():
                    level = marks
                    title = stripped[marks:].strip()
            elif re.match(r"^(\d+(?:\.\d+)*)\s+.{3,}$", stripped):
                level = stripped.split()[0].count(".") + 1
                title = stripped
            if level:
                headings.append((offset, offset + len(line), title, level))
            offset += len(line)

        if not raw_text.strip():
            return []
        if not headings:
            title = (metadata or {}).get("title") or "Untitled section"
            return [
                SectionCandidate(
                    title=title,
                    level=1,
                    source_char_start=0,
                    source_char_end=len(raw_text),
                    summary=self.summarize_text(raw_text),
                    confidence=0.6,
                )
            ]

        candidates: list[SectionCandidate] = []
        for index, (heading_start, heading_end, title, level) in enumerate(headings):
            end = headings[index + 1][0] if index + 1 < len(headings) else len(raw_text)
            start = heading_start
            body = raw_text[start:end]
            candidates.append(
                SectionCandidate(
                    title=title,
                    level=level,
                    source_char_start=start,
                    source_char_end=end,
                    summary=self.summarize_text(body),
                    confidence=0.72,
                )
            )
        return candidates

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------
    def generate_document_artifact(self, artifact_type: str, document_id: str, sections: list[Section]) -> AIArtifact:
        content = self._fallback_artifact_content(artifact_type, sections)
        grounding = self.grounding.check_artifact_grounding(content, sections)
        confidence = grounding["confidence"]
        return AIArtifact(
            id=new_id("art"),
            document_id=document_id,
            section_id=None,
            artifact_type=artifact_type,  # type: ignore[arg-type]
            content=content,
            grounding=grounding["references"],
            model=self.model,
            prompt_version=self.prompt_version,
            created_at=iso_now(),
            confidence=confidence,
            metadata={"source": "openai" if self.has_api_key else "fallback", "warnings": grounding["warnings"]},
        )

    def generate_section_summary(self, section_text: str) -> str:
        return self.summarize_text(section_text)

    def generate_summary(self, document_id: str, raw_text: str, sections: list[Section]) -> AIArtifact:
        return self.generate_document_artifact("summary", document_id, sections)

    def generate_faq(self, document_id: str, raw_text: str, sections: list[Section]) -> AIArtifact:
        return self.generate_document_artifact("faq", document_id, sections)

    def generate_critique(self, document_id: str, raw_text: str, sections: list[Section]) -> AIArtifact:
        return self.generate_document_artifact("critique", document_id, sections)

    def generate_takeaways(self, document_id: str, raw_text: str, sections: list[Section]) -> AIArtifact:
        return self.generate_document_artifact("takeaways", document_id, sections)

    def agent_reply(self, agent_role: str, thread_context: dict[str, Any], user_message: str) -> str:
        section: Section | None = thread_context.get("section")
        grounded_answer = thread_context.get("answer", "")
        quote = self._snippet(section.verbatim_content if section else "", 260)
        if agent_role == "expert_agent":
            content = (
                "As the Expert Agent, I would defend the selected content by grounding the answer in the "
                f"section's original wording: \"{quote}\". The strongest grounded response is:\n\n"
                f"{grounded_answer or user_message}"
            )
        elif agent_role == "critique_agent":
            content = (
                "As the Critique Agent, I see the selected section as the key evidence, but I would ask "
                "whether its claims are sufficiently supported, scoped, and operationalized. "
                f"Relevant source excerpt: \"{quote}\"."
            )
        else:
            content = (
                "As the Inexpert Agent, I would restate the section in simpler terms and ask what the core "
                f"terms mean. The part I am relying on is: \"{quote}\"."
            )
        return content + f"\n\nGrounded in section {section.id if section else 'unknown'}."

    def decompose_query(self, query: str, context: dict[str, Any] | None = None) -> list[str]:
        terms = [part.strip() for part in re.split(r"\band\b|[;?]", query, flags=re.I) if part.strip()]
        if len(terms) <= 1:
            return [query]
        return terms[:4]

    def compose_grounded_answer(self, query: str, subanswers: list[str], references: list[dict[str, Any]]) -> str:
        bullets = "\n".join(f"- {answer}" for answer in subanswers)
        return f"Grounded answer to: {query}\n{bullets}\n\nCitations: " + ", ".join(
            sorted({ref.get("section_id", "") for ref in references if ref.get("section_id")})
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def summarize_text(self, text: str, max_chars: int = 360) -> str:
        clean = " ".join(text.strip().split())
        if not clean:
            return "No source text was available for this section."
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        summary = " ".join(sentences[:2])
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip() + "…"
        return summary

    def _fallback_artifact_content(self, artifact_type: str, sections: list[Section]) -> str:
        title_list = ", ".join(section.title for section in sections[:5]) or "the document"
        snippets = [self._snippet(section.verbatim_content, 180) for section in sections[:4]]
        if artifact_type == "summary":
            return "AI Summary (fallback-local): This document contains sections on " + title_list + ".\n\n" + "\n".join(
                f"- {section.title}: {self.summarize_text(section.verbatim_content, 220)}" for section in sections[:8]
            )
        if artifact_type == "faq":
            return (
                "FAQ (AI-generated, grounded in source sections)\n"
                "Beginner: What is this document about?\n"
                f"Answer: It discusses {title_list}.\n\n"
                "Intermediate: Which sections should I inspect first?\n"
                f"Answer: Start with {title_list} and compare their original text.\n\n"
                "Expert: What evidence anchors the main claims?\n"
                f"Answer: Review these source excerpts: {' | '.join(snippets)}"
            )
        if artifact_type == "critique":
            return (
                "Critique (AI-generated):\n"
                f"Strongest claims appear in: {title_list}.\n"
                "Weakest claims are any statements not backed by explicit evidence in the original sections.\n"
                "Missing assumptions: verify definitions, scope, and methodology.\n"
                "Counterarguments: check whether the cited sections rule out alternative explanations.\n"
                "Strengthening evidence: add experiments, examples, or citations linked to the claims."
            )
        if artifact_type == "takeaways":
            return (
                "Takeaways (AI-generated):\n"
                "5 short takeaways:\n"
                + "\n".join(f"{i + 1}. Remember {section.title}." for i, section in enumerate(sections[:5]))
                + "\n\n3 deep takeaways:\n1. Preserve source wording while analyzing it.\n2. Tie claims to explicit sections.\n3. Separate interpretation from evidence.\n\n"
                "3 what to remember later points:\n1. Re-read original sections.\n2. Inspect AI grounding.\n3. Validate weak claims.\n\n"
                "3 possible applications:\n1. Literature review.\n2. Technical onboarding.\n3. Research discussion."
            )
        return self.summarize_text("\n".join(section.verbatim_content for section in sections))

    def _snippet(self, text: str, max_chars: int) -> str:
        clean = " ".join(text.strip().split())
        return clean[: max_chars - 1].rstrip() + "…" if len(clean) > max_chars else clean
