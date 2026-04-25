"""Dialogs for document-level AI artifacts."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget

from loci.models.schemas import AIArtifact
from loci.ui.widgets import Card, LabelPill


class ArtifactDialog(QDialog):
    """Show generated summaries, FAQs, critiques, and takeaways."""

    def __init__(self, title: str, artifacts: list[AIArtifact], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 620)
        content = QWidget()
        layout = QVBoxLayout(content)
        if not artifacts:
            layout.addWidget(QLabel("No AI artifact exists for this document yet."))
        for artifact in artifacts:
            card = Card()
            card.add_header(artifact.artifact_type.title(), LabelPill("AI-generated", "ai"))
            meta = QLabel(
                f"Model: {artifact.model} • Prompt: {artifact.prompt_version} • "
                f"Confidence: {artifact.confidence if artifact.confidence is not None else 'n/a'}"
            )
            meta.setObjectName("muted")
            body = QLabel(artifact.content)
            body.setWordWrap(True)
            card.layout().addWidget(meta)
            card.layout().addWidget(body)
            refs = QLabel("Grounding: " + ", ".join(ref.get("section_id", "?") for ref in artifact.grounding[:8]))
            refs.setObjectName("muted")
            refs.setWordWrap(True)
            card.layout().addWidget(refs)
            layout.addWidget(card)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
