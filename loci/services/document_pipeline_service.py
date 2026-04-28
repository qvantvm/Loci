"""AI document pipeline facade used by the agent panel composer."""

from __future__ import annotations

from dataclasses import dataclass

from loci.models.schemas import AgentScratchpad, AgentScratchpadEntry, Scope
from loci.services.agent_orchestrator import AgentOrchestrator, AgentRunResult
from loci.services.storage_service import StorageService


@dataclass
class PipelineResult:
    """Display-ready result from a document pipeline."""

    scratchpad_id: str
    final_answer: str
    generated_document_id: str | None = None


class DocumentPipelineService:
    """Run Research, Book Writer, Bottom-Up, and Graph Narrative pipelines."""

    PIPELINES = ("Research", "Book Writer", "Bottom-Up Synthesis", "Graph Narrative")

    def __init__(self, storage: StorageService, orchestrator: AgentOrchestrator) -> None:
        self.storage = storage
        self.orchestrator = orchestrator

    def run(self, pipeline: str, prompt: str, scope: Scope) -> PipelineResult:
        pipeline = pipeline if pipeline in self.PIPELINES else "Research"
        if pipeline == "Research":
            result = self._run_research(prompt, scope)
        elif pipeline == "Book Writer":
            result = self._run_structured_document(
                pipeline,
                prompt,
                scope,
                ["Table of Contents", "Chapter Outline", "Draft Sections", "Quality Loop", "References"],
            )
        elif pipeline == "Bottom-Up Synthesis":
            result = self._run_structured_document(
                pipeline,
                prompt,
                scope,
                ["Atomic Ideas", "Semantic Clusters", "Proposed Outline", "Draft Sections", "Coherence Pass"],
            )
        else:
            result = self._run_structured_document(
                pipeline,
                prompt,
                scope,
                ["Claims", "Evidence", "Knowledge Graph", "Narrative Order", "Coherence Pass"],
            )
        return PipelineResult(
            scratchpad_id=result.scratchpad.id,
            final_answer=result.final_answer,
            generated_document_id=result.generated_document_id,
        )

    def _run_research(self, prompt: str, scope: Scope) -> AgentRunResult:
        complexity = "Deep" if len(prompt.split()) > 12 or "why" in prompt.lower() else "Simple"
        if complexity == "Simple":
            result = self.orchestrator.answer_user_question(prompt, scope, max_iterations=3)
            result.scratchpad.pipeline = "Research"
            result.scratchpad.metadata = result.scratchpad.metadata | {"classification": complexity}
            self.storage.update_scratchpad(result.scratchpad)
            return result

        scratchpad = self.storage.create_scratchpad(
            AgentScratchpad(
                kind="pipeline",
                status="running",
                document_id=scope.document_id,
                section_id=scope.section_id,
                question=prompt,
                pipeline="Research",
                max_iterations=10,
                metadata={"classification": complexity, "scope": scope.model_dump()},
            )
        )
        stages = [
            ("planner", "Planner decomposes the question into sub-questions."),
            ("retriever", "Retriever gathers local evidence for each sub-question."),
            ("extractor", "Extractor pulls discrete grounded claims from the evidence."),
            ("critique_agent", "Critic identifies gaps, contradictions, and missing angles."),
            ("judge", "Judge decides the local evidence is sufficient for this first pass."),
            ("synthesizer", "Synthesizer compiles a final Markdown report."),
        ]
        evidence = self.orchestrator.rce.answer_query(prompt, scope)
        for index, (actor, content) in enumerate(stages, start=1):
            self.storage.create_scratchpad_entry(
                AgentScratchpadEntry(
                    scratchpad_id=scratchpad.id,
                    actor=actor,  # type: ignore[arg-type]
                    iteration=index,
                    entry_type="evidence" if actor == "retriever" else "note",
                    content=f"{content}\n\n{evidence.answer if actor in {'retriever', 'synthesizer'} else ''}".strip(),
                    grounding=evidence.citations,
                    confidence=evidence.confidence,
                    metadata={"pipeline": "Research"},
                )
            )
        final = (
            "# Research Report\n\n"
            f"## Question\n\n{prompt}\n\n"
            f"## Synthesis\n\n{evidence.answer}\n\n"
            "## Evidence Notes\n\n"
            "This report uses local Loci sources first; outside web search is not configured in this desktop build."
        )
        document, _sections = self.storage.create_generated_document(
            "AI: Research Report",
            final,
            evidence.citations,
            {"generated_by": "research_pipeline", "source_scratchpad_id": scratchpad.id},
        )
        scratchpad.status = "completed"
        scratchpad.iteration_count = len(stages)
        scratchpad.final_answer = final
        self.storage.update_scratchpad(scratchpad)
        return AgentRunResult(scratchpad=scratchpad, final_answer=final, generated_document_id=document.id)

    def _run_structured_document(
        self,
        pipeline: str,
        prompt: str,
        scope: Scope,
        stages: list[str],
    ) -> AgentRunResult:
        scratchpad = self.storage.create_scratchpad(
            AgentScratchpad(
                kind="pipeline",
                status="running",
                document_id=scope.document_id,
                section_id=scope.section_id,
                question=prompt,
                pipeline=pipeline,
                max_iterations=10,
                metadata={"scope": scope.model_dump()},
            )
        )
        evidence = self.orchestrator.rce.answer_query(prompt, scope)
        for index, stage in enumerate(stages, start=1):
            self.storage.create_scratchpad_entry(
                AgentScratchpadEntry(
                    scratchpad_id=scratchpad.id,
                    actor="synthesizer" if index == len(stages) else "planner",
                    iteration=index,
                    entry_type="note",
                    content=f"{pipeline} stage: {stage}.",
                    grounding=evidence.citations,
                    confidence=evidence.confidence,
                    metadata={"pipeline": pipeline},
                )
            )
        final = (
            f"# {pipeline}: {prompt}\n\n"
            + "\n\n".join(f"## {stage}\n\n{evidence.answer}" for stage in stages)
        )
        document, _sections = self.storage.create_generated_document(
            f"AI: {pipeline}",
            final,
            evidence.citations,
            {"generated_by": pipeline, "source_scratchpad_id": scratchpad.id},
        )
        scratchpad.status = "completed"
        scratchpad.iteration_count = len(stages)
        scratchpad.final_answer = final
        self.storage.update_scratchpad(scratchpad)
        return AgentRunResult(scratchpad=scratchpad, final_answer=final, generated_document_id=document.id)
