"""Left-side knowledge library and section navigator."""

from __future__ import annotations

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:  # pragma: no cover - import guard for service-only test environments
    raise

from loci.services.storage_service import StorageService
from loci.ui.widgets import Badge


class LeftLibraryPane(QWidget):
    """Document library with expandable section tree."""

    section_selected = Signal(str)
    upload_requested = Signal()
    paste_requested = Signal()

    def __init__(self, storage: StorageService) -> None:
        super().__init__()
        self.storage = storage
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search library…")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_item_clicked)

        upload = QPushButton("Upload")
        paste = QPushButton("Paste")
        upload.clicked.connect(self.upload_requested.emit)
        paste.clicked.connect(self.paste_requested.emit)

        header = QHBoxLayout()
        header.addWidget(QLabel("Knowledge Library"))
        header.addStretch()
        header.addWidget(Badge("Original + AI"))

        buttons = QHBoxLayout()
        buttons.addWidget(upload)
        buttons.addWidget(paste)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.search)
        layout.addLayout(buttons)
        layout.addWidget(self.tree)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        for document in self.storage.list_documents():
            doc_item = QTreeWidgetItem(
                [
                    f"{document.title}\n"
                    f"{document.source_type.upper()} • {document.created_at.date().isoformat()}"
                ]
            )
            doc_item.setData(0, 32, {"document_id": document.id})
            self.tree.addTopLevelItem(doc_item)
            section_items: dict[str, QTreeWidgetItem] = {}
            sections = self.storage.list_sections(document.id)
            for section in sections:
                figures = len(self.storage.list_figures(section_id=section.id))
                equations = len(self.storage.list_equations(section_id=section.id))
                artifacts = len(self.storage.list_artifacts(section_id=section.id))
                summary = (section.ai_summary or "No AI summary yet").strip().replace("\n", " ")
                if len(summary) > 100:
                    summary = summary[:97] + "…"
                suffix = f"  🖼 {figures}  ∑ {equations}  ✦ {artifacts}"
                item = QTreeWidgetItem([f"{'  ' * max(section.level - 1, 0)}{section.title}{suffix}\n{summary}"])
                item.setData(0, 32, {"document_id": document.id, "section_id": section.id})
                parent = section_items.get(section.parent_id or "")
                if parent is not None:
                    parent.addChild(item)
                else:
                    doc_item.addChild(item)
                section_items[section.id] = item
            doc_item.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, 32) or {}
        section_id = payload.get("section_id")
        if section_id:
            self.section_selected.emit(section_id)
