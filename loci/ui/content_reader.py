"""Center pane for rendering original content and AI annotations."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

try:  # pragma: no cover - depends on optional WebEngine availability.
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None  # type: ignore[assignment]

from loci.models.schemas import Equation, Figure, Section
from loci.services.storage_service import StorageService
from loci.ui.widgets import Badge, Card, LabelValue


class ContentReader(QWidget):
    """Render the selected section with strict source/AI separation."""

    section_changed = Signal(str, str)

    def __init__(self, storage: StorageService) -> None:
        super().__init__()
        self.storage = storage
        self.current_section: Section | None = None
        self.markdown = MarkdownIt("commonmark", {"breaks": True, "html": False})
        self.document_flow = QVBoxLayout()
        self.document_flow.setContentsMargins(0, 0, 0, 0)
        self.document_flow.setSpacing(12)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(18, 14, 18, 18)
        self.body_layout.setSpacing(10)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Loci Reader")
        self.title.setObjectName("editorTab")
        tab_bar = QFrame()
        tab_bar.setObjectName("tabBar")
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        tab_layout.addWidget(self.title)
        tab_layout.addStretch()
        title_row.addStretch()
        title_row.addWidget(Badge("Original content is never rewritten"))
        self.body_layout.addWidget(tab_bar)
        self.body_layout.addLayout(title_row)
        self.body_layout.addLayout(self.document_flow)
        self.body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        title_suffix = " [AI]" if document and document.source_type == "ai_generated" else ""
        document_title = document.title if document else section.document_id
        self.title.setText(f"{document_title}{title_suffix}")
        self._render_document_sections(section)
        self.section_changed.emit(section.document_id, section.id)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_document_sections(self, selected: Section) -> None:
        self._clear_layout(self.document_flow)
        sections = self.storage.list_sections(selected.document_id)
        start = next((index for index, section in enumerate(sections) if section.id == selected.id), 0)
        for index, section in enumerate(sections[start:], start=start):
            self.document_flow.addWidget(self._section_card(section, index == start))
        self.document_flow.addStretch()

    def _section_card(self, section: Section, highlighted: bool = False) -> QWidget:
        section_flow = QVBoxLayout()
        section_flow.setContentsMargins(0, 0, 0, 0)
        section_flow.setSpacing(8)
        meta = QLabel(f"<b>Section:</b> {escape(section.id)}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        section_flow.addWidget(meta)
        self._render_section_source(section, section_flow)
        badge = "selected" if highlighted else "source"
        return Card(section.title, self._layout_widget(section_flow), badge)

    def _render_section_source(self, section: Section, flow: QVBoxLayout) -> None:
        content = section.verbatim_content
        section_start = section.source_char_start or 0
        anchored: list[dict[str, Any]] = []
        unanchored: list[dict[str, Any]] = []
        for figure in self.storage.list_figures(section_id=section.id):
            item = {"kind": "figure", "value": figure, **self._relative_span(figure.metadata, section_start)}
            (anchored if item["start"] is not None else unanchored).append(item)
        for equation in self.storage.list_equations(section_id=section.id):
            item = {"kind": "equation", "value": equation, **self._relative_span(equation.metadata, section_start)}
            (anchored if item["start"] is not None else unanchored).append(item)

        cursor = 0
        for item in sorted(anchored, key=self._source_item_sort_key):
            start = max(0, min(item["start"], len(content)))
            end = max(start, min(item["end"] or start, len(content)))
            if start > cursor:
                self._add_markdown_chunk(content[cursor:start], flow)
            flow.addWidget(self._media_widget(item))
            cursor = max(cursor, end)
        if cursor < len(content):
            self._add_markdown_chunk(content[cursor:], flow)
        for item in sorted(unanchored, key=self._source_item_sort_key):
            flow.addWidget(self._media_widget(item))

    @staticmethod
    def _relative_span(metadata: dict[str, Any], section_start: int) -> dict[str, int | None]:
        start = metadata.get("source_char_start")
        end = metadata.get("source_char_end")
        if not isinstance(start, int):
            return {"start": None, "end": None}
        return {"start": max(0, start - section_start), "end": max(start, end) - section_start if isinstance(end, int) else None}

    @staticmethod
    def _source_item_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        metadata = item["value"].metadata
        start = item.get("start")
        if start is not None:
            return (0, start, item.get("end") or start)
        order_key = metadata.get("order_key")
        if isinstance(order_key, list):
            return (1, *order_key)
        bbox = item["value"].bbox or (0, 0, 0, 0)
        return (1, item["value"].page_number or 0, bbox[1], bbox[0], item["value"].id)

    def _add_markdown_chunk(self, text: str, flow: QVBoxLayout) -> None:
        if not text.strip():
            return
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        browser.setHtml(self._markdown_html(text))
        browser.document().setTextWidth(760)
        browser.setMinimumHeight(max(48, int(browser.document().size().height()) + 20))
        flow.addWidget(browser)

    def _markdown_html(self, text: str) -> str:
        html = self.markdown.render(text)
        return f"""
        <!doctype html>
        <html><head><style>
        body {{
            background: transparent;
            color: #C7CBD3;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 12px;
            line-height: 1.5;
            margin: 0;
        }}
        h1, h2, h3, h4 {{ color: #F2F3F5; line-height: 1.25; margin: 16px 0 8px; }}
        h1 {{ font-size: 22px; }}
        h2 {{ font-size: 18px; }}
        h3 {{ font-size: 15px; }}
        p {{ margin: 8px 0; }}
        ul, ol {{ margin: 8px 0 8px 22px; padding: 0; }}
        blockquote {{
            border-left: 3px solid #4C89FF;
            color: #AEB5C2;
            margin: 12px 0;
            padding: 2px 0 2px 12px;
        }}
        code {{
            background: #10131A;
            border: 1px solid #272C36;
            border-radius: 5px;
            color: #DDE1E8;
            padding: 1px 4px;
        }}
        pre {{
            background: #10131A;
            border: 1px solid #272C36;
            border-radius: 8px;
            margin: 12px 0;
            padding: 12px;
            white-space: pre-wrap;
        }}
        a {{ color: #8AB4FF; }}
        table {{ border-collapse: collapse; margin: 12px 0; }}
        th, td {{ border: 1px solid #303747; padding: 6px 8px; }}
        </style></head><body>{html}</body></html>
        """

    def _media_widget(self, item: dict[str, Any]) -> QWidget:
        value = item["value"]
        if item["kind"] == "figure":
            return self._figure_widget(value)
        return self._equation_widget(value)

    def _figure_widget(self, figure: Figure) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(8)
        self._add_figure_image(inner, figure.crop_path)
        if figure.caption:
            caption = QLabel(figure.caption)
            caption.setObjectName("muted")
            caption.setWordWrap(True)
            inner.addWidget(caption)
        inner.addWidget(LabelValue("Figure ID", figure.id))
        return frame

    def _load_figures(self, section: Section) -> None:
        figures = self.storage.list_figures(section_id=section.id)
        if not figures:
            return
        for figure in figures:
            self.document_flow.addWidget(self._figure_widget(figure))

    @staticmethod
    def _add_figure_image(layout: QVBoxLayout, crop_path: str) -> None:
        image_path = Path(crop_path)
        if not image_path.exists():
            label = QLabel(f"Image not found: {escape(crop_path)}")
            label.setObjectName("muted")
            label.setWordWrap(True)
            layout.addWidget(label)
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
        equations = self.storage.list_equations(section_id=section.id)
        if not equations:
            return
        for equation in equations:
            self.document_flow.addWidget(self._equation_widget(equation))

    def _equation_widget(self, equation: Equation) -> QWidget:
        container = QFrame()
        container.setObjectName("card")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
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
            view.setMinimumHeight(168)
            view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            view.page().setBackgroundColor(QColor("#151821"))
            html = self._mathjax_html(equation.mathjax)
            view.setHtml(html)
            layout.addWidget(view)
        else:
            fallback = QLabel(f"<pre>{escape(equation.mathjax)}</pre>")
            fallback.setWordWrap(True)
            layout.addWidget(fallback)
        layout.addWidget(source)
        return container

    @staticmethod
    def _mathjax_html(expression: str) -> str:
        display = ContentReader._display_math(expression)
        escaped = escape(display)
        return f"""
        <!doctype html>
        <html><head>
        <meta name="color-scheme" content="dark">
        <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            }},
            svg: {{ fontCache: 'global' }},
            startup: {{ typeset: true }}
        }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
        <style>
        html, body {{
            background: #151821;
            color: #E6E8EC;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            height: 100%;
            margin: 0;
            overflow: hidden;
        }}
        body {{
            align-items: center;
            box-sizing: border-box;
            display: flex;
            justify-content: center;
            padding: 14px 12px;
        }}
        #equation {{
            box-sizing: border-box;
            max-width: 100%;
            overflow-x: auto;
            overflow-y: hidden;
            padding: 4px 0;
            text-align: center;
            width: 100%;
        }}
        mjx-container {{
            color: #E6E8EC !important;
            margin: 0 !important;
            min-width: 0 !important;
            overflow-x: auto;
            overflow-y: hidden;
            padding: 2px 0;
        }}
        </style>
        </head><body><div id="equation">{escaped}</div></body></html>
        """

    @staticmethod
    def _display_math(expression: str) -> str:
        stripped = expression.strip()
        if stripped.startswith("$$") or stripped.startswith(r"\[") or stripped.startswith(r"\("):
            return stripped
        return rf"\[{stripped}\]"

