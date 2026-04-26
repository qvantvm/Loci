"""Left-side knowledge library and section navigator."""

from __future__ import annotations

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import (
        QFrame,
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
        self.search.setObjectName("sidebarSearch")
        self.search.setPlaceholderText("Search library…")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemClicked.connect(self._on_item_clicked)

        upload = QPushButton("Import")
        upload.setObjectName("primaryButton")
        paste = QPushButton("Paste")
        upload.clicked.connect(self.upload_requested.emit)
        paste.clicked.connect(self.paste_requested.emit)

        title = QLabel("LIBRARY")
        title.setObjectName("PaneTitle")
        header_frame = QFrame()
        header_frame.setObjectName("panelHeader")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(10, 9, 10, 9)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(Badge("Source + AI"))

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(upload)
        buttons.addWidget(paste)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_frame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)
        body_layout.addWidget(self.search)
        body_layout.addLayout(buttons)
        body_layout.addWidget(self.tree)
        layout.addWidget(body)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        root_item = QTreeWidgetItem(["LOCI"])
        root_item.setData(0, 32, {})
        self.tree.addTopLevelItem(root_item)
        for document in self.storage.list_documents():
            doc_item = QTreeWidgetItem([document.title])
            doc_item.setToolTip(0, f"{document.source_type.upper()} • {document.created_at.date().isoformat()}")
            doc_item.setData(0, 32, {"document_id": document.id})
            root_item.addChild(doc_item)
            section_items: dict[str, QTreeWidgetItem] = {}
            sections = self.storage.list_sections(document.id)
            for section in sections:
                item = QTreeWidgetItem([section.title])
                if section.ai_summary:
                    item.setToolTip(0, section.ai_summary.strip())
                item.setData(0, 32, {"document_id": document.id, "section_id": section.id})
                parent = section_items.get(section.parent_id or "")
                if parent is not None:
                    parent.addChild(item)
                else:
                    doc_item.addChild(item)
                section_items[section.id] = item
            doc_item.setExpanded(True)
        root_item.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, 32) or {}
        section_id = payload.get("section_id")
        if section_id:
            self.section_selected.emit(section_id)
