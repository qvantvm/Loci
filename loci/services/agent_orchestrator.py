"""Bounded multi-agent orchestration for dreaming and question answering."""

from __future__ import annotations

from dataclasses import dataclass

from loci.models.schemas import AgentScratchpad, AgentScratchpadEntry, GroundedAnswer, Scope, Section
from loci.services.grounding_service import GroundingService
from loci.services.openai_service import OpenAIService
from loci.services.recursive_context_engine import RecursiveContextEngine
from loci.services.storage_service import StorageService


@dataclass
class AgentRunResult:
    """Result of a completed scratchpad run."""

    scratchpad: AgentScratchpad
    final_answer: str
    generated_document_id: str | None = None


class AgentOrchestrator:
    """Coordinate Expert, Critique, and Beginner agents through a shared pad."""

    def __init__(
        self,
        storage: StorageService,
        rce: RecursiveContextEngine | None = None,
        openai: OpenAIService | None = None,
        grounding: GroundingService | None = None,
    ) -> None:
        self.storage = storage
        self.rce = rce or RecursiveContextEngine(storage)
        self.openai = openai or OpenAIService()
        self.grounding = grounding or GroundingService()

    def run_dream_cycle(self, scope: Scope | None = None, max_iterations: int = 10) -> AgentRunResult:
        """Let agents discuss stored content and persist grounded Expert-approved output."""

        scope = scope or Scope()
        max_iterations = self._clamp_iterations(max_iterations)
        scratchpad = self.storage.create_scratchpad(
            AgentScratchpad(
                kind="dream",
                status="running",
                document_id=scope.document_id,
                section_id=scope.section_id,
                question="Dream over saved Loci content and surface grounded questions, gaps, and synthesis.",
                max_iterations=max_iterations,
                metadata={"scope": scope.model_dump()},
            )
        )
        result = self._run_agent_loop(
            scratchpad,
            "What questions, gaps, and grounded synthesis emerge from the saved content?",
            scope,
            should_create_document=True,
        )
        return result

    def answer_user_question(self, question: str, scope: Scope | None = None, max_iterations: int = 10) -> AgentRunResult:
        """Create a fresh collaborative scratchpad and return the Expert-final answer."""

        scope = scope or Scope()
        max_iterations = self._clamp_iterations(max_iterations)
        scratchpad = self.storage.create_scratchpad(
            AgentScratchpad(
                kind="question",
                status="running",
                document_id=scope.document_id,
                section_id=scope.section_id,
                question=question,
                max_iterations=max_iterations,
                metadata={"scope": scope.model_dump()},
            )
        )
        return self._run_agent_loop(scratchpad, question, scope, should_create_document=False)

    def _run_agent_loop(
        self,
        scratchpad: AgentScratchpad,
        question: str,
        scope: Scope,
        should_create_document: bool,
    ) -> AgentRunResult:
        final_answer = ""
        generated_document_id: str | None = None
        confidence = 0.0
        grounding_refs: list[dict] = []

        try:
            for iteration in range(1, scratchpad.max_iterations + 1):
                evidence = self.rce.answer_query(question, scope)
                grounding_refs = evidence.citations
                sections = self._sections_for_grounding(scope, grounding_refs)

                beginner = self._beginner_entry(scratchpad.id, iteration, question, evidence)
                self.storage.create_scratchpad_entry(beginner)

                critic = self._critic_entry(scratchpad.id, iteration, evidence)
                self.storage.create_scratchpad_entry(critic)

                candidate = self._expert_candidate(question, evidence, critic.content, scratchpad.kind)
                grounding = self.grounding.check_artifact_grounding(candidate, sections)
                confidence = grounding["confidence"]
                final_answer = candidate
                expert = AgentScratchpadEntry(
                    scratchpad_id=scratchpad.id,
                    actor="expert_agent",
                    iteration=iteration,
                    entry_type="decision" if confidence >= 0.2 else "critique",
                    content=self._expert_decision(candidate, confidence, grounding["warnings"]),
                    grounding=grounding["references"] or grounding_refs,
                    confidence=confidence,
                    metadata={"warnings": grounding["warnings"], "model": self.openai.model},
                )
                self.storage.create_scratchpad_entry(expert)

                scratchpad.iteration_count = iteration
                if confidence >= 0.2:
                    break

            scratchpad.status = "completed"
            scratchpad.final_answer = final_answer
            scratchpad.metadata = scratchpad.metadata | {"confidence": confidence, "grounding": grounding_refs}
            self.storage.update_scratchpad(scratchpad)

            if should_create_document and final_answer and confidence >= 0.2:
                document, _sections = self.storage.create_generated_document(
                    title=self._generated_title(final_answer),
                    markdown=final_answer,
                    grounding=grounding_refs,
                    metadata={
                        "generated_by": "expert_agent",
                        "source_scratchpad_id": scratchpad.id,
                        "confidence": confidence,
                    },
                )
                generated_document_id = document.id
                self.storage.create_scratchpad_entry(
                    AgentScratchpadEntry(
                        scratchpad_id=scratchpad.id,
                        actor="expert_agent",
                        iteration=scratchpad.iteration_count,
                        entry_type="artifact",
                        content=f"Created AI-generated document: {document.title}",
                        grounding=grounding_refs,
                        confidence=confidence,
                        metadata={"document_id": document.id},
                    )
                )
            return AgentRunResult(scratchpad=scratchpad, final_answer=final_answer, generated_document_id=generated_document_id)
        except Exception as exc:
            scratchpad.status = "failed"
            scratchpad.metadata = scratchpad.metadata | {"error": str(exc)}
            self.storage.update_scratchpad(scratchpad)
            raise

    def _beginner_entry(
        self,
        scratchpad_id: str,
        iteration: int,
        question: str,
        evidence: GroundedAnswer,
    ) -> AgentScratchpadEntry:
        content = (
            f"Beginner question for iteration {iteration}: What should a reader understand about "
            f"'{question}'? The clearest grounded clue is: {self._snippet(evidence.answer, 420)}"
        )
        return AgentScratchpadEntry(
            scratchpad_id=scratchpad_id,
            actor="inexpert_agent",
            iteration=iteration,
            entry_type="question",
            content=content,
            grounding=evidence.citations,
            confidence=evidence.confidence,
            metadata={"model": evidence.model},
        )

    def _critic_entry(self, scratchpad_id: str, iteration: int, evidence: GroundedAnswer) -> AgentScratchpadEntry:
        content = (
            "Critique: keep the final answer limited to cited source material, define ambiguous terms, "
            "and avoid any claim that cannot be traced to the retrieved sections."
        )
        if not evidence.citations:
            content += " No citations were found, so the Expert should not approve new content."
        return AgentScratchpadEntry(
            scratchpad_id=scratchpad_id,
            actor="critique_agent",
            iteration=iteration,
            entry_type="critique",
            content=content,
            grounding=evidence.citations,
            confidence=evidence.confidence,
            metadata={"model": evidence.model},
        )

    def _expert_candidate(self, question: str, evidence: GroundedAnswer, critique: str, kind: str) -> str:
        heading = "Dream Synthesis" if kind == "dream" else "Answer"
        citations = sorted({ref.get("section_id", "") for ref in evidence.citations if ref.get("section_id")})
        citation_text = ", ".join(citations) if citations else "No grounded section citations found"
        return (
            f"# {heading}\n\n"
            f"## Question\n\n{question}\n\n"
            f"## Grounded Response\n\n{self._snippet(evidence.answer, 1400)}\n\n"
            f"## Critique Check\n\n{critique}\n\n"
            f"## Citations\n\n{citation_text}\n"
        )

    @staticmethod
    def _expert_decision(candidate: str, confidence: float, warnings: list[str]) -> str:
        if confidence >= 0.2:
            return f"Expert decision: approved as grounded with confidence {confidence:.2f}.\n\n{candidate}"
        warning_text = "\n".join(f"- {warning}" for warning in warnings) or "- Insufficient grounding."
        return f"Expert decision: not approved yet. Grounding confidence {confidence:.2f}.\n\n{warning_text}"

    def _sections_for_grounding(self, scope: Scope, refs: list[dict]) -> list[Section]:
        section_ids = [ref.get("section_id") for ref in refs if isinstance(ref.get("section_id"), str)]
        if scope.section_id:
            section_ids.append(scope.section_id)
        if scope.section_ids:
            section_ids.extend(scope.section_ids)
        sections: list[Section] = []
        seen: set[str] = set()
        for section_id in section_ids:
            if section_id in seen:
                continue
            section = self.storage.get_section(section_id)
            if section:
                sections.append(section)
                seen.add(section.id)
        if sections:
            return sections
        if scope.document_id:
            return self.storage.list_sections(scope.document_id)
        return self.storage.list_sections()

    @staticmethod
    def _clamp_iterations(max_iterations: int) -> int:
        return max(1, min(10, max_iterations))

    @staticmethod
    def _snippet(text: str, max_chars: int) -> str:
        clean = " ".join(text.strip().split())
        return clean[: max_chars - 1].rstrip() + "..." if len(clean) > max_chars else clean

    @staticmethod
    def _generated_title(markdown: str) -> str:
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return f"AI: {title}"
        return "AI: Dream Synthesis"
