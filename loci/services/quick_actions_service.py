"""Context-sensitive AI action helpers for the right panel."""

from __future__ import annotations

from loci.models.schemas import ResearchFragment, Section, new_id
from loci.services.openai_service import OpenAIService
from loci.services.storage_service import StorageService


class QuickActionsService:
    """Implement lightweight section, chapter, and document actions."""

    def __init__(self, storage: StorageService, openai: OpenAIService | None = None) -> None:
        self.storage = storage
        self.openai = openai or OpenAIService()

    def run_section_action(self, section_id: str, action: str) -> ResearchFragment | None:
        section = self.storage.get_section(section_id)
        if not section:
            return None
        content = self._section_action_content(section, action)
        return self.storage.create_research_fragment(
            ResearchFragment(
                title=f"{action}: {section.title}",
                content=content,
                document_id=section.document_id,
                section_id=section.id,
                grounding=[{"document_id": section.document_id, "section_id": section.id, "confidence": 0.7}],
                metadata={"action": action, "source": "quick_action", "model": self.openai.model},
            )
        )

    def run_document_action(self, document_id: str, action: str) -> ResearchFragment:
        sections = self.storage.list_sections(document_id)
        title = self.storage.get_document(document_id).title if self.storage.get_document(document_id) else document_id
        summaries = "\n".join(f"- {section.title}: {section.ai_summary}" for section in sections[:12])
        content = f"# {action}: {title}\n\n{self._document_action_intro(action)}\n\n{summaries}"
        return self.storage.create_research_fragment(
            ResearchFragment(
                title=f"{action}: {title}",
                content=content,
                document_id=document_id,
                grounding=[{"document_id": document_id, "section_id": section.id, "confidence": 0.5} for section in sections[:8]],
                metadata={"action": action, "source": "quick_action", "model": self.openai.model},
            )
        )

    def promote_fragment(self, fragment_id: str, parent_id: str | None = None) -> Section | None:
        fragment = self.storage.get_research_fragment(fragment_id)
        if not fragment or not fragment.document_id:
            return None
        parent = self.storage.get_section(parent_id) if parent_id else None
        section = self.storage.create_section(
            Section(
                id=new_id("sec"),
                document_id=fragment.document_id,
                parent_id=parent_id,
                title=fragment.title,
                level=min(6, (parent.level if parent else 0) + 1),
                order_index=len(self.storage.list_sections(fragment.document_id)),
                verbatim_content=fragment.content,
                ai_summary=self.openai.summarize_text(fragment.content),
                metadata={
                    "status": "ai_suggested",
                    "provenance": "ai_generated",
                    "promoted_fragment_id": fragment.id,
                    "grounding": fragment.grounding,
                },
            )
        )
        fragment.status = "promoted"
        fragment.section_id = section.id
        self.storage.update_research_fragment(fragment)
        return section

    def _section_action_content(self, section: Section, action: str) -> str:
        summary = self.openai.summarize_text(section.verbatim_content, 700)
        if action == "Expand":
            return f"# Expanded: {section.title}\n\n{summary}\n\nAdd examples, definitions, and implications grounded in the source text."
        if action == "Summarize":
            return f"# Summary: {section.title}\n\n{summary}"
        if action == "Critique":
            return (
                f"# Critique: {section.title}\n\n"
                "Check scope, undefined terms, missing evidence, and claims that need stronger support.\n\n"
                f"Source basis: {summary}"
            )
        if action == "Generate Questions":
            return (
                f"# Reader Questions: {section.title}\n\n"
                f"1. What is the main claim of {section.title}?\n"
                "2. What evidence supports it?\n"
                "3. What assumptions should be checked?\n"
            )
        if action == "Generate Title":
            return f"# Title Suggestions\n\n1. {section.title}\n2. A Grounded Guide to {section.title}\n3. Key Ideas in {section.title}"
        if action == "Split Section":
            return f"# Split Proposal: {section.title}\n\nSplit at natural heading or paragraph boundaries after the main setup and before detailed implications."
        if action == "Rewrite for Clarity":
            return f"# Clarity Rewrite: {section.title}\n\n{summary}"
        return f"# {action}: {section.title}\n\n{summary}"

    @staticmethod
    def _document_action_intro(action: str) -> str:
        if action == "Consistency Scan":
            return "Review the sections for contradictions, tone mismatches, undefined terms, and weak grounding."
        if action == "Duplicate Detection":
            return "Look for redundant or overlapping sections."
        if action == "Terminology Normalization":
            return "Identify terms that should be standardized across the document."
        if action == "Structure Critique":
            return "Evaluate document architecture and flow."
        return "Generated document-level action result."
