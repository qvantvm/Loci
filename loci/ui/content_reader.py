"""Center pane for rendering original content and AI annotations."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

try:  # pragma: no cover - depends on optional WebEngine availability.
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None  # type: ignore[assignment]

from loci.models.schemas import Equation, Section
from loci.services.storage_service import StorageService
from loci.ui.artifact_views import ArtifactDialog
from loci.ui.widgets import Badge, Card, LabelValue


class ContentReader(QWidget):
    """Render the selected section with strict source/AI separation."""

    section_changed = Signal(str, str)

    def __init__(self, storage: StorageService) -> None:
        super().__init__()
        self.storage = storage
        self.current_section: Section | None = None
        self.source_label = QLabel("Select a section to begin.")
        self.source_label.setWordWrap(True)
        self.ai_summary = QLabel("")
        self.ai_summary.setWordWrap(True)
        self.figures = QVBoxLayout()
        self.equations = QVBoxLayout()

        self.artifact_buttons: dict[str, QPushButton] = {}
        artifact_row = QHBoxLayout()
        for artifact_type, label in {
            "summary": "Whole Summary",
            "faq": "FAQ",
            "critique": "Critique",
            "takeaways": "Takeaways",
        }.items():
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, t=artifact_type: self.open_artifact(t))
            self.artifact_buttons[artifact_type] = button
            artifact_row.addWidget(button)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        title_row = QHBoxLayout()
        self.title = QLabel("Loci Reader")
        self.title.setObjectName("PaneTitle")
        title_row.addWidget(self.title)
        title_row.addStretch()
        title_row.addWidget(Badge("Original content is never rewritten"))
        self.body_layout.addLayout(title_row)
        self.body_layout.addLayout(artifact_row)
        self.body_layout.addWidget(Card("Original", self.source_label, "source"))
        self.body_layout.addWidget(Card("AI Summary", self.ai_summary, "ai"))
        self.body_layout.addWidget(Card("Figures", self._layout_widget(self.figures), "source"))
        self.body_layout.addWidget(Card("Equations", self._layout_widget(self.equations), "source"))
        self.body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

    @staticmethod
    def _layout_widget(layout: QVBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def load_section(self, section_id: str) -> None:
        section = self.storage.get_section(section_id)
        if not section:
            return
        self.current_section = section
        document = self.storage.get_document(section.document_id)
        self.title.setText(section.title)
        self.source_label.setText(
            f"<p><b>Document:</b> {escape(document.title if document else section.document_id)}</p>"
            f"<p><b>Section ID:</b> {escape(section.id)}</p>"
            f"<pre>{escape(section.verbatim_content)}</pre>"
        )
        self.ai_summary.setText(
            f"<p><b>AI-generated, grounded in:</b> {escape(section.id)}</p>"
            f"<p>{escape(section.ai_summary or 'No AI summary has been generated yet.')}</p>"
        )
        self._load_figures(section)
        self._load_equations(section)
        self.section_changed.emit(section.document_id, section.id)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _load_figures(self, section: Section) -> None:
        self._clear_layout(self.figures)
        figures = self.storage.list_figures(section_id=section.id)
        if not figures:
            self.figures.addWidget(QLabel("No extracted figures for this section."))
            return
        for figure in figures:
            frame = QFrame()
            inner = QVBoxLayout(frame)
            self._add_figure_image(inner, figure.crop_path)
            inner.addWidget(LabelValue("Figure ID", figure.id))
            inner.addWidget(LabelValue("Caption", figure.caption or "No source caption detected."))
            inner.addWidget(LabelValue("Bounding box", str(figure.bbox)))
            if figure.ai_description:
                inner.addWidget(LabelValue("AI description", figure.ai_description))
            self.figures.addWidget(frame)

    @staticmethod
    def _add_figure_image(layout: QVBoxLayout, crop_path: str) -> None:
        image_path = Path(crop_path)
        if not image_path.exists():
            return
        label = QLabel()
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(
                    420,
                    320,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setScaledContents(False)
            layout.addWidget(label)

    def _load_equations(self, section: Section) -> None:
        self._clear_layout(self.equations)
        equations = self.storage.list_equations(section_id=section.id)
        if not equations:
            self.equations.addWidget(QLabel("No extracted equations for this section."))
            return
        for equation in equations:
            self.equations.addWidget(self._equation_widget(equation))

    def _equation_widget(self, equation: Equation) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(LabelValue("Equation ID", equation.id))
        toggle = QCheckBox("Show source / MathJax")
        source = QLabel(
            f"<pre>{escape(equation.source_text or '')}</pre>"
            f"<pre>{escape(equation.mathjax)}</pre>"
        )
        source.setVisible(False)
        toggle.toggled.connect(source.setVisible)
        layout.addWidget(toggle)
        if QWebEngineView is not None:
            view = QWebEngineView()
            view.setMinimumHeight(110)
            html = self._mathjax_html(equation.mathjax)
            view.setHtml(html)
            layout.addWidget(view)
        else:
            layout.addWidget(QLabel(f"MathJax: {escape(equation.mathjax)}"))
        layout.addWidget(source)
        return container

    @staticmethod
    def _mathjax_html(expression: str) -> str:
        escaped = escape(expression)
        return f"""
        <!doctype html>
        <html><head>
        <script>
        window.MathJax = {{ tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }} }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
        <style>body {{ background: transparent; color: #dfe7ff; font-family: Inter, sans-serif; }}</style>
        </head><body><div>\\[{escaped}\\]</div></body></html>
        """

    def open_artifact(self, artifact_type: str) -> None:
        if not self.current_section:
            return
        dialog = ArtifactDialog(self.storage, self.current_section.document_id, artifact_type, self)
        dialog.exec()
