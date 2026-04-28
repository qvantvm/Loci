"""Local consistency checks for sections and documents."""

from __future__ import annotations

from collections import Counter

from loci.models.schemas import ConsistencyIssue, Section
from loci.services.grounding_service import GroundingService
from loci.services.storage_service import StorageService


class ConsistencyService:
    """Run deterministic quality scans that can later be backed by AI."""

    def __init__(self, storage: StorageService, grounding: GroundingService | None = None) -> None:
        self.storage = storage
        self.grounding = grounding or GroundingService()

    def scan_document(self, document_id: str) -> list[ConsistencyIssue]:
        sections = self.storage.list_sections(document_id)
        issues: list[ConsistencyIssue] = []
        title_counts = Counter(section.title.strip().lower() for section in sections)
        for section in sections:
            issues.extend(self._scan_section(section, sections))
            if title_counts[section.title.strip().lower()] > 1:
                issues.append(
                    ConsistencyIssue(
                        document_id=document_id,
                        section_id=section.id,
                        severity="warning",
                        category="Duplicate Title",
                        description=f"Multiple sections share the title '{section.title}'.",
                    )
                )
        if not sections:
            issues.append(
                ConsistencyIssue(
                    document_id=document_id,
                    severity="error",
                    category="Empty Document",
                    description="This document has no sections to scan.",
                )
            )
        return [self.storage.create_consistency_issue(issue) for issue in issues]

    def scan_section(self, section_id: str) -> list[ConsistencyIssue]:
        section = self.storage.get_section(section_id)
        if not section:
            return []
        sections = self.storage.list_sections(section.document_id)
        return [self.storage.create_consistency_issue(issue) for issue in self._scan_section(section, sections)]

    def _scan_section(self, section: Section, sections: list[Section]) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        if not section.verbatim_content.strip():
            issues.append(
                ConsistencyIssue(
                    document_id=section.document_id,
                    section_id=section.id,
                    severity="error",
                    category="Empty Section",
                    description="The section has no content.",
                )
            )
        if not section.ai_summary.strip():
            issues.append(
                ConsistencyIssue(
                    document_id=section.document_id,
                    section_id=section.id,
                    severity="warning",
                    category="Missing Summary",
                    description="The section does not have an AI summary.",
                )
            )
        if section.metadata.get("provenance") == "ai_generated":
            grounding = self.grounding.check_artifact_grounding(section.verbatim_content, sections)
            if grounding["confidence"] < 0.2:
                issues.append(
                    ConsistencyIssue(
                        document_id=section.document_id,
                        section_id=section.id,
                        severity="warning",
                        category="Low Grounding",
                        description="AI-generated section content is weakly grounded in available source sections.",
                        metadata={"confidence": grounding["confidence"], "warnings": grounding["warnings"]},
                    )
                )
        if "TODO" in section.verbatim_content or "TBD" in section.verbatim_content:
            issues.append(
                ConsistencyIssue(
                    document_id=section.document_id,
                    section_id=section.id,
                    severity="warning",
                    category="Draft Marker",
                    description="The section still contains TODO/TBD markers.",
                )
            )
        return issues
