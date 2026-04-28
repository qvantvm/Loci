"""Left-side knowledge library and section navigator."""

from __future__ import annotations

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QPushButton,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:  # pragma: no cover - import guard for service-only test environments
    raise

from loci.services.storage_service import StorageService
from loci.models.schemas import Section, new_id
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
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)

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
            is_ai = document.source_type == "ai_generated"
            doc_item = QTreeWidgetItem([f"{document.title}  [AI]" if is_ai else document.title])
            provenance = "AI-generated document" if is_ai else document.source_type.upper()
            doc_item.setToolTip(0, f"{provenance} • {document.created_at.date().isoformat()}")
            doc_item.setData(0, 32, {"document_id": document.id})
            root_item.addChild(doc_item)
            section_items: dict[str, QTreeWidgetItem] = {}
            sections = self.storage.list_sections(document.id)
            for section in sections:
                section_is_ai = section.metadata.get("provenance") == "ai_generated" or is_ai
                item = QTreeWidgetItem([f"{section.title}  [AI]" if section_is_ai else section.title])
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

    def _open_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if not item:
            return
        payload = item.data(0, 32) or {}
        document_id = payload.get("document_id")
        section_id = payload.get("section_id")
        if not document_id:
            return
        menu = QMenu(self)
        add_section = menu.addAction("Add Section")
        add_chapter = menu.addAction("Add Chapter")
        rename = menu.addAction("Rename")
        promote = menu.addAction("Promote to Chapter")
        delete = menu.addAction("Delete")
        promote.setEnabled(bool(section_id))
        delete.setEnabled(bool(section_id))
        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        if action == add_section:
            self._add_section(document_id, section_id)
        elif action == add_chapter:
            self._add_section(document_id, None, chapter=True)
        elif action == rename:
            self._rename(document_id, section_id)
        elif action == promote and section_id:
            self._promote_section(section_id)
        elif action == delete and section_id:
            self._delete_section(section_id)

    def _add_section(self, document_id: str, parent_id: str | None, chapter: bool = False) -> None:
        title, ok = QInputDialog.getText(self, "Add Chapter" if chapter else "Add Section", "Title:")
        if not ok or not title.strip():
            return
        sibling_count = len(self.storage.list_sections(document_id))
        level = 1
        if parent_id and not chapter:
            parent = self.storage.get_section(parent_id)
            level = min(6, (parent.level if parent else 1) + 1)
        section = Section(
            id=new_id("sec"),
            document_id=document_id,
            parent_id=None if chapter else parent_id,
            title=title.strip(),
            level=1 if chapter else level,
            order_index=sibling_count,
            verbatim_content=f"# {title.strip()}\n\n",
            ai_summary="",
            metadata={"status": "draft", "provenance": "ai_generated", "source_preservation": "manual_ai_section"},
        )
        self.storage.create_section(section)
        self.refresh()
        self.section_selected.emit(section.id)

    def _rename(self, document_id: str, section_id: str | None) -> None:
        if section_id:
            section = self.storage.get_section(section_id)
            if not section:
                return
            title, ok = QInputDialog.getText(self, "Rename Section", "Title:", text=section.title)
            if ok and title.strip():
                section.title = title.strip()
                self.storage.update_section(section)
        else:
            document = self.storage.get_document(document_id)
            if not document:
                return
            title, ok = QInputDialog.getText(self, "Rename Document", "Title:", text=document.title)
            if ok and title.strip():
                document.title = title.strip()
                self.storage.update_document(document)
        self.refresh()

    def _promote_section(self, section_id: str) -> None:
        section = self.storage.get_section(section_id)
        if not section:
            return
        section.parent_id = None
        section.level = 1
        self.storage.update_section(section)
        self.refresh()
        self.section_selected.emit(section.id)

    def _delete_section(self, section_id: str) -> None:
        section = self.storage.get_section(section_id)
        if not section:
            return
        answer = QMessageBox.question(self, "Delete Section", f"Delete '{section.title}'?")
        if answer == QMessageBox.StandardButton.Yes:
            self.storage.delete_section(section_id)
            self.refresh()
