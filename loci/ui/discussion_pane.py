"""Agent workspace with dreaming, scratchpads, actions, references, and scans."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from loci.models.schemas import AgentScratchpad, AgentScratchpadEntry, ContentReference, DiscussionMessage, Scope
from loci.services.agent_orchestrator import AgentOrchestrator
from loci.services.consistency_service import ConsistencyService
from loci.services.document_pipeline_service import DocumentPipelineService
from loci.services.openai_service import AIProvider, OpenAIService
from loci.services.quick_actions_service import QuickActionsService
from loci.services.recursive_context_engine import RecursiveContextEngine
from loci.services.storage_service import StorageService
from loci.ui.widgets import Card, LabelValue


class AgentTaskWorker(QObject):
    """Run an agent task away from the Qt UI thread."""

    finished = Signal(str, str, object)
    failed = Signal(str, str, str)

    def __init__(self, task_id: str, task_kind: str, task: Callable[[], object]) -> None:
        super().__init__()
        self.task_id = task_id
        self.task_kind = task_kind
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.task_id, self.task_kind, self.task())
        except Exception as exc:
            self.failed.emit(self.task_id, self.task_kind, str(exc))


class DiscussionPane(QWidget):
    """Threaded discussion plus durable multi-agent scratchpads."""

    messages_changed = Signal()

    def __init__(
        self,
        storage: StorageService,
        rce: RecursiveContextEngine,
        openai: OpenAIService,
        orchestrator: AgentOrchestrator | None = None,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.rce = rce
        self.openai = openai
        self.orchestrator = orchestrator or AgentOrchestrator(storage, rce, openai)
        self.pipeline_service = DocumentPipelineService(storage, self.orchestrator)
        self.quick_actions = QuickActionsService(storage, openai)
        self.consistency = ConsistencyService(storage)
        self.section_id: str | None = None
        self.thread_id: str | None = None
        self.document_id: str | None = None
        self.agent_tasks: dict[str, tuple[QThread, AgentTaskWorker]] = {}

        self.title = QLabel("AGENTS")
        self.title.setObjectName("PaneTitle")
        header = QFrame()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 9, 10, 9)
        header_layout.addWidget(self.title)
        header_layout.addStretch()

        self.tabs = QTabWidget()
        self.dream_flow = self._new_flow()
        self.question_flow = self._new_flow()
        self.actions_flow = self._new_flow()
        self.references_flow = self._new_flow()
        self.consistency_flow = self._new_flow()
        self.tabs.addTab(self._scroll_widget(self.dream_flow), "Dreaming")
        self.tabs.addTab(self._scroll_widget(self.question_flow), "Question")
        self.tabs.addTab(self._scroll_widget(self.actions_flow), "Actions")
        self.tabs.addTab(self._scroll_widget(self.references_flow), "References")
        self.tabs.addTab(self._scroll_widget(self.consistency_flow), "Consistency")

        self.input = QTextEdit()
        self.input.setPlaceholderText("Ask about the selected section or enter a pipeline topic...")
        self.input.setMaximumHeight(96)

        self.pipeline_combo = QComboBox()
        self.pipeline_combo.addItems(list(DocumentPipelineService.PIPELINES))
        self.dream_provider_combo = QComboBox()
        self.dream_provider_combo.addItem("Dream: LM Studio", "local")
        self.dream_provider_combo.addItem("Dream: OpenAI", "openai")
        self.dream_provider_combo.addItem("Dream: Fallback", "fallback")
        self.ask_question_button = QPushButton("Ask / Run")
        self.dream_button = QPushButton("Dream Cycle")
        self.ask_question_button.clicked.connect(self._run_composer)
        self.dream_button.clicked.connect(self._run_dream_cycle)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self.pipeline_combo)
        controls.addWidget(self.dream_provider_combo)
        controls.addWidget(self.ask_question_button)
        controls.addWidget(self.dream_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)
        body_layout.addWidget(self.tabs)
        body_layout.addWidget(self.input)
        body_layout.addLayout(controls)
        layout.addWidget(body)
        self._render_action_buttons()

    def load_section(self, section_id: str) -> None:
        section = self.storage.get_section(section_id)
        if not section:
            return
        self.section_id = section_id
        self.document_id = section.document_id
        thread = self.storage.get_or_create_root_thread(section.document_id, section.id)
        self.thread_id = thread.id
        self.title.setText("AGENTS")
        self._ensure_dreaming()
        self.refresh()

    def refresh(self) -> None:
        self._clear_flow(self.dream_flow)
        self._clear_flow(self.question_flow)
        self._clear_flow(self.references_flow)
        self._clear_flow(self.consistency_flow)
        self._render_dreaming()
        self._render_questions()
        self._render_references()
        self._render_consistency()

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

    def _run_composer(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or not self.thread_id or not self.section_id:
            return
        self.storage.create_message(DiscussionMessage(thread_id=self.thread_id, actor="user", content=text))
        section = self.storage.get_section(self.section_id)
        scope = Scope(document_id=section.document_id if section else None, section_id=self.section_id)
        pipeline = self.pipeline_combo.currentText()
        thread_id = self.thread_id
        self.input.clear()
        self.refresh()

        def task() -> dict[str, Any]:
            result = self.pipeline_service.run(pipeline, text, scope)
            return {"result": result, "thread_id": thread_id, "pipeline": pipeline}

        self._start_agent_task("composer", task)

    def _complete_composer_task(self, payload: dict[str, Any]) -> None:
        result = payload["result"]
        thread_id = payload["thread_id"]
        pipeline = payload["pipeline"]
        entries = self.storage.list_scratchpad_entries(result.scratchpad_id)
        expert_entry = next((entry for entry in reversed(entries) if entry.actor in {"expert_agent", "synthesizer"}), None)
        self.storage.create_message(
            DiscussionMessage(
                thread_id=thread_id,
                actor="expert_agent",
                content=result.final_answer,
                grounding=expert_entry.grounding if expert_entry else [],
                confidence=expert_entry.confidence if expert_entry else None,
                metadata={
                    "scratchpad_id": result.scratchpad_id,
                    "generated_document_id": result.generated_document_id,
                    "pipeline": pipeline,
                    "model": self.openai.model,
                },
            )
        )
        self.refresh()
        self.messages_changed.emit()

    def _run_dream_cycle(self) -> None:
        if not self.section_id:
            return
        section = self.storage.get_section(self.section_id)
        scope = Scope(document_id=section.document_id if section else None, section_id=self.section_id)
        provider = self._dream_provider()
        self._start_agent_task(
            "dream",
            lambda: self.orchestrator.run_dream_cycle(scope, max_iterations=10, provider=provider),
        )

    def _ensure_dreaming(self) -> None:
        if not self.section_id:
            return
        existing = self.storage.list_scratchpads(kind="dream", section_id=self.section_id, limit=1)
        if not existing:
            self._run_dream_cycle()

    def _start_agent_task(self, task_kind: str, task: Callable[[], object]) -> None:
        if task_kind in self._running_task_kinds():
            return
        task_id = f"agent_task_{uuid4().hex}"
        worker = AgentTaskWorker(task_id, task_kind, task)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._agent_task_finished)
        worker.failed.connect(self._agent_task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda task_id=task_id: self._cleanup_agent_task(task_id))
        self.agent_tasks[task_id] = (thread, worker)
        self._set_task_busy(task_kind, True)
        thread.start()

    def _agent_task_finished(self, task_id: str, task_kind: str, result: object) -> None:
        if task_kind == "composer" and isinstance(result, dict):
            self._complete_composer_task(result)
        else:
            self.refresh()
            self.messages_changed.emit()
        self._set_task_busy(task_kind, False)

    def _agent_task_failed(self, task_id: str, task_kind: str, error: str) -> None:
        if self.thread_id:
            self.storage.create_message(
                DiscussionMessage(
                    thread_id=self.thread_id,
                    actor="expert_agent",
                    content=f"Agent task failed: {error}",
                    metadata={"task_id": task_id, "task_kind": task_kind},
                )
            )
        self.refresh()
        self.messages_changed.emit()
        self._set_task_busy(task_kind, False)

    def _cleanup_agent_task(self, task_id: str) -> None:
        if task := self.agent_tasks.pop(task_id, None):
            task[0].deleteLater()

    def _running_task_kinds(self) -> set[str]:
        return {worker.task_kind for _thread, worker in self.agent_tasks.values()}

    def _set_task_busy(self, task_kind: str, busy: bool) -> None:
        if task_kind == "dream":
            self.dream_button.setEnabled(not busy)
            self.dream_button.setText("Dreaming..." if busy else "Dream Cycle")
        if task_kind == "composer":
            self.ask_question_button.setEnabled(not busy)
            self.ask_question_button.setText("Working..." if busy else "Ask / Run")

    def _dream_provider(self) -> AIProvider:
        value = self.dream_provider_combo.currentData()
        return value if value in {"local", "openai", "fallback"} else "fallback"  # type: ignore[return-value]

    def _render_dreaming(self) -> None:
        pads = self.storage.list_scratchpads(kind="dream", section_id=self.section_id, limit=5) if self.section_id else []
        if not pads:
            self.dream_flow.addWidget(QLabel("No dream scratchpad has run for this section yet."))
        for pad in pads:
            self.dream_flow.addWidget(self._scratchpad_card(pad))
        self.dream_flow.addStretch()

    def _render_questions(self) -> None:
        if self.thread_id:
            for message in self.storage.list_messages(self.thread_id):
                self.question_flow.addWidget(self._message_card(message))
        pads = self.storage.list_scratchpads(kind="question", section_id=self.section_id, limit=5) if self.section_id else []
        for pad in pads:
            self.question_flow.addWidget(self._scratchpad_card(pad))
        self.question_flow.addStretch()

    def _scratchpad_card(self, pad: AgentScratchpad) -> QWidget:
        card = Card(f"{pad.kind.title()} Scratchpad", f"{pad.status} • {pad.iteration_count}/{pad.max_iterations}")
        if pad.question:
            card.addWidget(LabelValue("Question", pad.question))
        if pad.final_answer:
            label = QLabel(pad.final_answer[:900])
            label.setWordWrap(True)
            card.addWidget(label)
        for entry in self.storage.list_scratchpad_entries(pad.id)[-8:]:
            card.addWidget(self._entry_widget(entry))
        return card

    def _entry_widget(self, entry: AgentScratchpadEntry) -> QWidget:
        role = entry.actor.replace("_", " ").title()
        card = Card(f"{entry.iteration}. {role}", entry.entry_type)
        label = QLabel(entry.content)
        label.setWordWrap(True)
        card.addWidget(label)
        if entry.confidence is not None:
            card.addWidget(LabelValue("Confidence", f"{entry.confidence:.2f}"))
        if entry.grounding:
            refs = ", ".join(ref.get("section_id", "?") for ref in entry.grounding[:5])
            card.addWidget(LabelValue("Grounding", refs))
        return card

    def _render_action_buttons(self) -> None:
        self._clear_flow(self.actions_flow)
        section_actions = [
            "Expand",
            "Summarize",
            "Critique",
            "Generate Title",
            "Generate Questions",
            "Split Section",
            "Rewrite for Clarity",
            "Expand Derivation",
            "Generate Figure",
            "Add Exercises",
            "Reorganize",
        ]
        doc_actions = ["Consistency Scan", "Duplicate Detection", "Terminology Normalization", "Structure Critique"]
        self.actions_flow.addWidget(QLabel("Section Actions"))
        for action in section_actions:
            button = QPushButton(action)
            button.clicked.connect(lambda _=False, a=action: self._run_section_action(a))
            self.actions_flow.addWidget(button)
        self.actions_flow.addWidget(QLabel("Document Actions"))
        for action in doc_actions:
            button = QPushButton(action)
            button.clicked.connect(lambda _=False, a=action: self._run_document_action(a))
            self.actions_flow.addWidget(button)
        cleanup = QPushButton("Clean AI Generated Content")
        cleanup.clicked.connect(self._clean_ai_generated_content)
        self.actions_flow.addWidget(cleanup)
        self.actions_flow.addStretch()

    def _run_section_action(self, action: str) -> None:
        if self.section_id:
            self.quick_actions.run_section_action(self.section_id, action)
            self.refresh()

    def _run_document_action(self, action: str) -> None:
        if self.document_id:
            self.quick_actions.run_document_action(self.document_id, action)
            if action == "Consistency Scan":
                self.consistency.scan_document(self.document_id)
            self.refresh()

    def _clean_ai_generated_content(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clean AI Generated Content",
            "Remove generated documents, scratchpads, fragments, AI artifacts, traces, embeddings, and AI agent messages? Imported source files and source sections will be preserved.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        counts = self.storage.clean_ai_generated_content(delete_agent_messages=True)
        self.refresh()
        self.messages_changed.emit()
        QMessageBox.information(
            self,
            "AI Content Cleaned",
            "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in counts.items()),
        )

    def _render_references(self) -> None:
        if not self.section_id:
            self.references_flow.addWidget(QLabel("Select a section to see references."))
            self.references_flow.addStretch()
            return
        add_reference = QPushButton("Add Related Reference")
        add_reference.clicked.connect(self._add_related_reference)
        self.references_flow.addWidget(add_reference)
        references = self.storage.list_references(self.section_id)
        if not references:
            self.references_flow.addWidget(QLabel("No explicit cross-references yet. Grounding references appear in messages and scratchpads."))
        for reference in references:
            card = Card(reference.relationship.title())
            card.addWidget(LabelValue("Source", reference.source_section_id))
            card.addWidget(LabelValue("Target", reference.target_section_id))
            if reference.anchor_text:
                card.addWidget(LabelValue("Anchor", reference.anchor_text))
            self.references_flow.addWidget(card)
        fragments = self.storage.list_research_fragments()
        for fragment in [item for item in fragments if item.section_id == self.section_id][:5]:
            card = Card(f"Research Inbox: {fragment.title}", fragment.status)
            label = QLabel(fragment.content[:500])
            label.setWordWrap(True)
            card.addWidget(label)
            promote = QPushButton("Add to Manuscript")
            promote.clicked.connect(lambda _=False, fragment_id=fragment.id: self._promote_fragment(fragment_id))
            promote.setEnabled(fragment.status == "inbox")
            card.addWidget(promote)
            self.references_flow.addWidget(card)
        self.references_flow.addStretch()

    def _promote_fragment(self, fragment_id: str) -> None:
        section = self.quick_actions.promote_fragment(fragment_id, self.section_id)
        if section:
            self.refresh()
            self.messages_changed.emit()

    def _add_related_reference(self) -> None:
        if not self.section_id or not self.document_id:
            return
        sections = [section for section in self.storage.list_sections(self.document_id) if section.id != self.section_id]
        if not sections:
            return
        labels = [f"{section.title} ({section.id})" for section in sections]
        label, ok = QInputDialog.getItem(self, "Add Reference", "Target section:", labels, 0, False)
        if not ok or not label:
            return
        target = sections[labels.index(label)]
        relationship, ok = QInputDialog.getItem(
            self,
            "Relationship",
            "Type:",
            ["related", "supports", "contradicts", "extends", "summarizes", "cites"],
            0,
            False,
        )
        if not ok:
            return
        anchor, _ = QInputDialog.getText(self, "Anchor Text", "Optional anchor text:")
        self.storage.create_reference(
            ContentReference(
                source_section_id=self.section_id,
                target_section_id=target.id,
                relationship=relationship,  # type: ignore[arg-type]
                anchor_text=anchor.strip() or None,
            )
        )
        self.refresh()

    def _render_consistency(self) -> None:
        controls = QHBoxLayout()
        scan_section = QPushButton("Scan Section")
        scan_document = QPushButton("Scan Document")
        scan_section.clicked.connect(self._scan_section)
        scan_document.clicked.connect(self._scan_document)
        controls.addWidget(scan_section)
        controls.addWidget(scan_document)
        holder = QWidget()
        holder.setLayout(controls)
        self.consistency_flow.addWidget(holder)
        if not self.document_id:
            self.consistency_flow.addWidget(QLabel("Select a section to scan."))
            self.consistency_flow.addStretch()
            return
        issues = self.storage.list_consistency_issues(self.document_id, self.section_id)
        if not issues:
            self.consistency_flow.addWidget(QLabel("No consistency issues recorded for this scope."))
        for issue in issues[:20]:
            card = Card(issue.category, issue.severity)
            label = QLabel(issue.description)
            label.setWordWrap(True)
            card.addWidget(label)
            if issue.section_id:
                card.addWidget(LabelValue("Section", issue.section_id))
            self.consistency_flow.addWidget(card)
        self.consistency_flow.addStretch()

    def _scan_section(self) -> None:
        if self.section_id:
            self.consistency.scan_section(self.section_id)
            self.refresh()

    def _scan_document(self) -> None:
        if self.document_id:
            self.consistency.scan_document(self.document_id)
            self.refresh()

    def _latest_user_message(self) -> str:
        if not self.thread_id:
            return ""
        for message in reversed(self.storage.list_messages(self.thread_id)):
            if message.actor == "user":
                return message.content
        return ""

    @staticmethod
    def _new_flow() -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        return layout

    @staticmethod
    def _scroll_widget(layout: QVBoxLayout) -> QScrollArea:
        holder = QWidget()
        holder.setLayout(layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        return scroll

    @staticmethod
    def _clear_flow(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
