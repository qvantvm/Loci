"""Reusable PySide6 widgets for card-like Loci surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """A rounded card with a vertical layout."""

    def __init__(self, title: str | None = None, badge: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(8)
        if title or badge:
            row = QHBoxLayout()
            if title:
                heading = QLabel(title)
                heading.setObjectName("cardTitle")
                row.addWidget(heading)
            row.addStretch(1)
            if badge:
                badge_label = QLabel(badge)
                badge_label.setObjectName("badge")
                row.addWidget(badge_label)
            self.layout.addLayout(row)


class Badge(QLabel):
    """Small semantic label for source/AI/metadata distinctions."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")

