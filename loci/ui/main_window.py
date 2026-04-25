"""Main PySide6 window for Loci."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
)

from loci.services.ingestion_pipeline import IngestionPipeline
from loci.services.openai_service import OpenAIService
from loci.services.recursive_context_engine import RecursiveContextEngine
from loci.services.storage_service import StorageService
from loci.ui.artifact_views import ArtifactDialog
from loci.ui.content_reader import ContentReader
from loci.ui.discussion_pane import DiscussionPane
from loci.ui.left_library_pane import LeftLibraryPane
from loci.ui.theme import apply_theme


class MainWindow(QMainWindow):
    """Three-pane shell: library, content reader, and discussion."""

    def __init__(self, storage: StorageService | None = None) -> None:
        super().__init__()
        self.storage = storage or StorageService()
        self.openai = OpenAIService()
        self.pipeline = IngestionPipeline(self.storage, self.openai)
        self.rce = RecursiveContextEngine(self.storage, openai=self.openai)
        self.current_section_id: str | None = None
        self.dark = False

        self.library = LeftLibraryPane(self.storage)
        self.reader = ContentReader(self.storage)
        self.discussion = DiscussionPane(self.storage, self.rce, self.openai)

        self.library.section_selected.connect(self.open_section)
        self.library.upload_requested.connect(self.upload_file)
        self.library.paste_requested.connect(self.paste_text)
        self.reader.artifact_requested.connect(self.show_artifact)
        self.discussion.messages_changed.connect(self.library.refresh)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.library)
        splitter.addWidget(self.reader)
        splitter.addWidget(self.discussion)
        splitter.setSizes([320, 680, 420])
        self.setCentralWidget(splitter)

        self._build_toolbar()
        apply_theme(self, dark=False)
        self.setWindowTitle("Loci — Visual AI Knowledge Base")
        self.resize(1440, 920)
        self._ensure_demo_content()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Loci")
        self.addToolBar(toolbar)
        toolbar.addAction("Upload File", self.upload_file)
        toolbar.addAction("Paste Text", self.paste_text)
        toolbar.addAction("Refresh", self.refresh)
        toolbar.addAction("Toggle Theme", self.toggle_theme)

    def refresh(self) -> None:
        self.library.refresh()
        if self.current_section_id:
            self.open_section(self.current_section_id)

    def toggle_theme(self) -> None:
        self.dark = not self.dark
        apply_theme(self, self.dark)

    def open_section(self, section_id: str) -> None:
        self.current_section_id = section_id
        self.reader.load_section(section_id)
        self.discussion.load_section(section_id)

    def upload_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload document",
            str(Path.home()),
            "Documents (*.pdf *.md *.markdown *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            result = self.pipeline.ingest_file(path)
        except Exception as exc:  # pragma: no cover - GUI safety net
            QMessageBox.critical(self, "Ingestion failed", str(exc))
            return
        self.refresh()
        if result.sections:
            self.open_section(result.sections[0].id)

    def paste_text(self) -> None:
        title, ok = QInputDialog.getText(self, "Document title", "Title:")
        if not ok:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Paste source text", "Original content:")
        if not ok or not text.strip():
            return
        try:
            result = self.pipeline.ingest_text(title or "Pasted Document", text, "pasted")
        except Exception as exc:  # pragma: no cover - GUI safety net
            QMessageBox.critical(self, "Ingestion failed", str(exc))
            return
        self.refresh()
        if result.sections:
            self.open_section(result.sections[0].id)

    def show_artifact(self, artifact_type: str) -> None:
        section = self.storage.get_section(self.current_section_id) if self.current_section_id else None
        if not section:
            return
        dialog = ArtifactDialog(self.storage, section.document_id, artifact_type, self)
        dialog.exec()

    def _ensure_demo_content(self) -> None:
        if self.storage.list_documents():
            return
        demo = """# Loci Demo

Loci keeps original source text sacred while AI-generated summaries, critiques, and discussions live in separate artifacts.

## Recursive Context

The Recursive Context Engine searches sections, reads only relevant snippets, and composes grounded answers with citations instead of stuffing the full corpus into one prompt.

## Equations

An example relation is E = mc^2. Equation candidates are stored separately from generated MathJax.
"""
        result = self.pipeline.ingest_text("Loci Demo", demo, "pasted")
        self.library.refresh()
        if result.sections:
            self.open_section(result.sections[0].id)
