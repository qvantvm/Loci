"""Reusable PySide6 widgets for card-like Loci surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """A rounded card with a vertical layout."""

    def __init__(
        self,
        title: str | None = None,
        body: QWidget | str | None = None,
        badge: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)

        if isinstance(body, str) and badge is None:
            badge = body
            body = None

        if title or badge:
            self.add_header(title or "", Badge(badge) if badge else None)
        if body is not None:
            self.addWidget(body)

    def add_header(self, title: str, badge: QWidget | None = None) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        row.addWidget(heading)
        row.addStretch(1)
        if badge is not None:
            row.addWidget(badge)
        self._layout.addLayout(row)

    def addWidget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class Badge(QLabel):
    """Small semantic label for source/AI/metadata distinctions."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")


class LabelPill(Badge):
    """Badge variant that can carry semantic style metadata."""

    def __init__(self, text: str, kind: str = "default", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("kind", kind)


class LabelValue(QWidget):
    """Compact metadata row with a bold label and wrapped value."""

    def __init__(self, label: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        key = QLabel(f"{label}:")
        key.setObjectName("metadataLabel")
        value_label = QLabel(value)
        value_label.setWordWrap(True)

        layout.addWidget(key)
        layout.addWidget(value_label, 1)

