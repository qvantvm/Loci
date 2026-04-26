from __future__ import annotations

from pathlib import Path

from loci.services.ingestion_pipeline import IngestionPipeline
from loci.services.storage_service import StorageService


def test_markdown_ingestion_preserves_original_and_creates_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    storage = StorageService(data_dir=tmp_path / "data")
    pipeline = IngestionPipeline(storage)
    source = "# Intro\nOriginal alpha beta.\n\n## Details\nEquation-ish: E = mc^2\n"

    result = pipeline.ingest_text("Paper", source, source_type="markdown")

    assert result.document.source_type == "markdown"
    assert Path(result.document.source_path or "").read_text(encoding="utf-8") == source
    assert [section.title for section in result.sections] == ["Intro", "Details"]
    assert result.sections[0].verbatim_content == "Original alpha beta.\n\n"
    assert result.sections[1].parent_id == result.sections[0].id
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "summary",
        "faq",
        "critique",
        "takeaways",
    }
    assert all(artifact.model == "fallback-local" for artifact in result.artifacts)


def test_txt_ingestion_without_headings_creates_single_verbatim_section(tmp_path: Path) -> None:
    storage = StorageService(data_dir=tmp_path / "data")
    pipeline = IngestionPipeline(storage)
    text = "A source paragraph with Bayesian inference.\nSecond paragraph is preserved."

    result = pipeline.ingest_text("Notes", text, source_type="pasted")

    assert len(result.sections) == 1
    assert result.sections[0].verbatim_content == text
    assert result.sections[0].title == "Notes"


def test_markdown_ingestion_records_media_order_metadata(tmp_path: Path) -> None:
    storage = StorageService(data_dir=tmp_path / "data")
    pipeline = IngestionPipeline(storage)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "diagram.png").write_bytes(b"not-a-real-image")
    markdown_path = source_dir / "paper.md"
    markdown = (
        "# Intro\n"
        "Before the figure.\n\n"
        "![Architecture](diagram.png \"System diagram\")\n\n"
        "$$\n"
        "a^2 + b^2 = c^2\n"
        "$$\n\n"
        "After the equation.\n"
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    result = pipeline.ingest_file(markdown_path)

    assert len(result.figures) == 1
    assert len(result.equations) == 1
    figure = result.figures[0]
    equation = result.equations[0]
    assert figure.section_id == result.sections[0].id
    assert equation.section_id == result.sections[0].id
    assert Path(figure.crop_path).name == "diagram.png"
    assert figure.caption == "System diagram"
    assert figure.metadata["source_char_start"] < equation.metadata["source_char_start"]
    assert figure.metadata["source_char_end"] <= equation.metadata["source_char_start"]
    assert equation.mathjax == "a^2 + b^2 = c^2"
