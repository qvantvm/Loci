"""Slack-like section discussion pane with grounded agent replies."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from loci.models.schemas import AgentRole, DiscussionMessage, Scope
from loci.services.openai_service import OpenAIService
from loci.services.recursive_context_engine import RecursiveContextEngine
from loci.services.storage_service import StorageService
from loci.ui.widgets import Card, LabelValue


class DiscussionPane(QWidget):
    """Threaded discussion for the currently selected section."""

    messages_changed = Signal()

    def __init__(self, storage: StorageService, rce: RecursiveContextEngine, openai: OpenAIService) -> None:
        super().__init__()
        self.storage = storage
        self.rce = rce
        self.openai = openai
        self.section_id: str | None = None
        self.thread_id: str | None = None

        self.title = QLabel("AGENTS")
        self.title.setObjectName("PaneTitle")
        header = QFrame()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 9, 10, 9)
        header_layout.addWidget(self.title)
        header_layout.addStretch()
        self.messages = QVBoxLayout()
        self.messages.setContentsMargins(0, 0, 0, 0)
        self.messages.setSpacing(10)
        self.messages.addStretch()
        message_holder = QWidget()
        message_holder.setLayout(self.messages)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(message_holder)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Ask about the selected section…")
        self.input.setMaximumHeight(96)

        ask_user = QPushButton("Send")
        ask_expert = QPushButton("Ask Expert")
        ask_critic = QPushButton("Ask Critic")
        ask_beginner = QPushButton("Ask Beginner")
        ask_all = QPushButton("Ask All")
        ask_user.clicked.connect(self._send_user)
        ask_expert.clicked.connect(lambda: self._ask_agent(AgentRole.EXPERT))
        ask_critic.clicked.connect(lambda: self._ask_agent(AgentRole.CRITIQUE))
        ask_beginner.clicked.connect(lambda: self._ask_agent(AgentRole.INEXPERT))
        ask_all.clicked.connect(self._ask_all)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        for button in (ask_user, ask_expert, ask_critic, ask_beginner, ask_all):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)
        body_layout.addWidget(scroll)
        body_layout.addWidget(self.input)
        body_layout.addLayout(buttons)
        layout.addWidget(body)

    def load_section(self, section_id: str) -> None:
        section = self.storage.get_section(section_id)
        if not section:
            return
        self.section_id = section_id
        thread = self.storage.get_or_create_root_thread(section.document_id, section.id)
        self.thread_id = thread.id
        self.title.setText("AGENTS")
        self.refresh()

    def refresh(self) -> None:
        while self.messages.count() > 1:
            item = self.messages.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        if not self.thread_id:
            return
        for message in self.storage.list_messages(self.thread_id):
            self.messages.insertWidget(self.messages.count() - 1, self._message_card(message))

    def _message_card(self, message: DiscussionMessage) -> QWidget:
        role = {
            "user": "User",
            "expert_agent": "Expert Agent",
            "critique_agent": "Critique Agent",
            "inexpert_agent": "Inexpert Agent",
        }.get(message.actor, message.actor)
        citations = ", ".join(
            ref.get("section_id", "")
            for ref in message.grounding
            if isinstance(ref, dict) and ref.get("section_id")
        )
        card = Card(role)
        card.addWidget(QLabel(message.content))
        if citations:
            card.addWidget(LabelValue("Grounding", citations))
        return card

    def _send_user(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or not self.thread_id:
            return
        message = DiscussionMessage(thread_id=self.thread_id, actor="user", content=text)
        self.storage.create_message(message)
        self.input.clear()
        self.refresh()
        self.messages_changed.emit()

    def _ask_agent(self, role: AgentRole) -> None:
        if not self.section_id or not self.thread_id:
            return
        question = self.input.toPlainText().strip() or self._latest_user_message() or "Discuss this section."
        answer = self.rce.answer_query(question, Scope(section_id=self.section_id))
        response = self.openai.agent_reply(role.value, {"answer": answer.answer, "citations": answer.citations}, question)
        message = DiscussionMessage(
            thread_id=self.thread_id,
            actor=role.value,  # type: ignore[arg-type]
            content=response,
            grounding=answer.citations,
            metadata={"model": answer.model, "confidence": answer.confidence},
        )
        self.storage.create_message(message)
        self.refresh()
        self.messages_changed.emit()

    def _ask_all(self) -> None:
        for role in (AgentRole.EXPERT, AgentRole.CRITIQUE, AgentRole.INEXPERT):
            self._ask_agent(role)

    def _latest_user_message(self) -> str:
        if not self.thread_id:
            return ""
        for message in reversed(self.storage.list_messages(self.thread_id)):
            if message.actor == "user":
                return message.content
        return ""
