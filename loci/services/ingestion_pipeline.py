"""End-to-end ingestion pipeline for source-preserving documents."""

from __future__ import annotations

from pathlib import Path

from loci.models.schemas import (
    AIArtifact,
    Equation,
    Figure,
    IngestionResult,
    ParsedDocument,
    Section,
    SectionCandidate,
    new_id,
)
from loci.services.embedding_service import EmbeddingService
from loci.services.grounding_service import GroundingService
from loci.services.markdown_service import MarkdownService
from loci.services.openai_service import OpenAIService
from loci.services.pdf_service import PDFService
from loci.services.storage_service import StorageService


class IngestionPipeline:
    """Parse, structure, store, embed, and artifact-generate source content."""

    def __init__(
        self,
        storage: StorageService | None = None,
        openai_service: OpenAIService | None = None,
        markdown_service: MarkdownService | None = None,
        pdf_service: PDFService | None = None,
        embedding_service: EmbeddingService | None = None,
        grounding_service: GroundingService | None = None,
    ) -> None:
        self.storage = storage or StorageService()
        self.openai = openai_service or OpenAIService()
        self.markdown = markdown_service or MarkdownService()
        self.pdf = pdf_service or PDFService(self.storage.crops_dir)
        self.embeddings = embedding_service or EmbeddingService(self.storage, self.openai)
        self.grounding = grounding_service or GroundingService()

    def ingest_text(self, title: str, text: str, source_type: str = "pasted") -> IngestionResult:
        suffix = ".md" if source_type == "markdown" else ".txt"
        source_path, digest = self.storage.save_pasted_source(text, suffix=suffix)
        parsed = self.markdown.parse(text, title=title, source_type=source_type)
        return self._persist_parsed(title, source_type, source_path, digest, parsed)

    def ingest_file(self, path: str | Path) -> IngestionResult:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        source_path, digest = self.storage.save_uploaded_source(file_path)
        if suffix == ".pdf":
            parsed = self.pdf.parse(Path(source_path))
            source_type = "pdf"
        elif suffix in {".md", ".markdown"}:
            parsed = self.markdown.parse(
                Path(source_path).read_text(encoding="utf-8"),
                file_path.stem,
                "markdown",
                base_dir=file_path.parent,
            )
            source_type = "markdown"
        elif suffix == ".txt":
            parsed = self.markdown.parse(
                Path(source_path).read_text(encoding="utf-8"),
                file_path.stem,
                "txt",
                base_dir=file_path.parent,
            )
            source_type = "txt"
        else:
            raise ValueError(f"Unsupported file type for ingestion: {suffix}")
        return self._persist_parsed(parsed.title or file_path.stem, source_type, source_path, digest, parsed)

    def _persist_parsed(
        self,
        title: str,
        source_type: str,
        source_path: str,
        digest: str,
        parsed: ParsedDocument,
    ) -> IngestionResult:
        warnings: list[str] = []
        document = self.storage.create_document(
            title=parsed.title or title,
            source_type=source_type,
            source_path=source_path,
            original_hash=digest,
            metadata=parsed.metadata,
        )

        candidates = parsed.sections or [
            SectionCandidate(
                title=parsed.title or title,
                level=1,
                source_char_start=0,
                source_char_end=len(parsed.raw_text),
                summary=self.openai.generate_section_summary(parsed.raw_text),
            )
        ]
        sections = self._store_sections(document.id, parsed.raw_text, candidates)
        section_by_span = sorted(sections, key=lambda item: (item.source_char_start or 0, item.source_char_end or 0))

        figures: list[Figure] = []
        for candidate in parsed.figures:
            span_start = self._metadata_int(candidate.metadata, "source_char_start")
            section_id = self._section_for_page_or_span(section_by_span, candidate.page_number, span_start)
            figures.append(
                self.storage.create_figure(
                    Figure(
                        id=new_id("fig"),
                        document_id=document.id,
                        section_id=section_id,
                        page_number=candidate.page_number,
                        bbox=candidate.bbox,
                        crop_path=candidate.crop_path,
                        caption=candidate.caption,
                        ai_description=None,
                        confidence=candidate.confidence,
                        metadata=candidate.metadata,
                    )
                )
            )

        equations: list[Equation] = []
        for candidate in parsed.equations:
            span_start = self._metadata_int(candidate.metadata, "source_char_start")
            section_id = self._section_for_page_or_span(section_by_span, candidate.page_number, span_start)
            equations.append(
                self.storage.create_equation(
                    Equation(
                        id=new_id("eq"),
                        document_id=document.id,
                        section_id=section_id,
                        page_number=candidate.page_number,
                        bbox=candidate.bbox,
                        source_text=candidate.source_text,
                        mathjax=candidate.mathjax,
                        confidence=candidate.confidence,
                        metadata=candidate.metadata,
                    )
                )
            )

        for section in sections:
            self.embeddings.embed_and_store(
                "section",
                section.id,
                f"{section.title}\n{section.ai_summary}\n{section.verbatim_content}",
                embedding_type="content",
            )

        artifacts = self._create_document_artifacts(document.id, parsed.raw_text, sections)
        if not sections:
            warnings.append("No sections were detected; document stored as a single source section.")
        return IngestionResult(
            document=document,
            sections=sections,
            figures=figures,
            equations=equations,
            artifacts=artifacts,
            warnings=warnings,
        )

    def _store_sections(self, document_id: str, raw_text: str, candidates: list[SectionCandidate]) -> list[Section]:
        sections: list[Section] = []
        stack: list[Section] = []
        for index, candidate in enumerate(sorted(candidates, key=lambda item: (item.source_char_start, item.source_char_end))):
            start = max(0, min(candidate.source_char_start, len(raw_text)))
            end = max(start, min(candidate.source_char_end, len(raw_text)))
            verbatim = raw_text[start:end]
            while stack and stack[-1].level >= candidate.level:
                stack.pop()
            parent = stack[-1] if stack else None
            section = Section(
                id=new_id("sec"),
                document_id=document_id,
                parent_id=parent.id if parent else None,
                title=candidate.title or f"Section {index + 1}",
                level=candidate.level,
                order_index=index,
                page_start=candidate.page_start,
                page_end=candidate.page_end,
                verbatim_content=verbatim,
                ai_summary=candidate.summary or self.openai.generate_section_summary(verbatim),
                source_char_start=start,
                source_char_end=end,
                metadata={"confidence": candidate.confidence, "source_preservation": "verbatim_slice"},
            )
            self.storage.create_section(section)
            sections.append(section)
            stack.append(section)
        return sections

    @staticmethod
    def _section_for_page_or_span(sections: list[Section], page: int | None, span_start: int | None) -> str | None:
        if span_start is not None:
            for section in sections:
                if (section.source_char_start or 0) <= span_start <= (section.source_char_end or 0):
                    return section.id
        if page is not None:
            for section in sections:
                if section.page_start is not None and section.page_end is not None and section.page_start <= page <= section.page_end:
                    return section.id
        return sections[0].id if sections else None

    @staticmethod
    def _metadata_int(metadata: dict[str, object], key: str) -> int | None:
        value = metadata.get(key)
        return value if isinstance(value, int) else None

    def _create_document_artifacts(self, document_id: str, raw_text: str, sections: list[Section]) -> list[AIArtifact]:
        source_sections = sections[:8]
        generated = [
            self.openai.generate_summary(document_id, raw_text, source_sections),
            self.openai.generate_faq(document_id, raw_text, source_sections),
            self.openai.generate_critique(document_id, raw_text, source_sections),
            self.openai.generate_takeaways(document_id, raw_text, source_sections),
        ]
        artifacts: list[AIArtifact] = []
        for artifact in generated:
            grounding = self.grounding.check_artifact_grounding(artifact.content, source_sections)
            artifact.grounding = grounding["references"]
            artifact.confidence = grounding["confidence"]
            artifact.metadata = artifact.metadata | {"warnings": grounding["warnings"]}
            artifacts.append(self.storage.create_artifact(artifact))
        return artifacts
