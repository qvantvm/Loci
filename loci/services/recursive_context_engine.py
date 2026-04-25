"""Controlled recursive access to the local knowledge environment."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from loci.models.schemas import GroundedAnswer, Scope, SearchResult, Section, ToolTrace, new_id
from loci.services.openai_service import OpenAIService
from loci.services.search_service import SearchService
from loci.services.storage_service import StorageService


@dataclass
class RecursiveContextEngine:
    """Answer questions by recursively searching and reading stored sections.

    The engine implements a controlled tool interface. It never executes
    arbitrary model-supplied code; all access happens through fixed Python
    methods that read/search the local SQLite-backed knowledge environment.
    """

    storage: StorageService
    search: SearchService | None = None
    openai: OpenAIService | None = None
    max_recursion_depth: int = 2
    max_tool_calls: int = 16
    max_tokens: int = 6_000
    trace_logging: bool = True
    _tool_calls: int = field(default=0, init=False)
    _trace: list[ToolTrace] = field(default_factory=list, init=False)
    _run_id: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.search = self.search or SearchService(self.storage)
        self.openai = self.openai or OpenAIService()

    def answer_query(self, query: str, scope: Scope) -> GroundedAnswer:
        """Return a grounded response with citations and replayable trace."""

        self._tool_calls = 0
        self._trace = []
        self._run_id = f"rce_{uuid4().hex}"
        answer = self._answer_recursive(query=query, scope=scope, depth=0)
        answer.trace = list(self._trace)
        return answer

    # ------------------------------------------------------------------
    # Recursive algorithm
    # ------------------------------------------------------------------
    def _answer_recursive(self, query: str, scope: Scope, depth: int) -> GroundedAnswer:
        results = self.search_sections(query, scope, limit=5, depth=depth)
        if not results:
            return GroundedAnswer(
                query=query,
                answer="I could not find grounded source material for this question in the selected scope.",
                citations=[],
                model=self.openai.model,
                confidence=0.1,
                trace=list(self._trace),
            )

        broad = len(results) >= 4 and depth < self.max_recursion_depth and self._tool_calls < self.max_tool_calls - 4
        if broad:
            subanswers: list[GroundedAnswer] = []
            for subquestion in self.create_subquestion(query, results[:3], depth):
                narrowed = Scope(document_id=scope.document_id, section_ids=[item.section_id for item in results[:3]])
                subanswers.append(self._answer_recursive(subquestion, narrowed, depth + 1))
            return self.compose_grounded_answer(query, subanswers, depth)

        sections = [section for result in results[:3] if (section := self.read_section(result.section_id, depth))]
        return self._direct_answer(query, sections, results)

    def _direct_answer(self, query: str, sections: list[Section], results: list[SearchResult]) -> GroundedAnswer:
        snippets: list[str] = []
        citations: list[dict] = []
        for section, result in zip(sections, results):
            quote = result.snippet or section.verbatim_content[:300]
            snippets.append(f"[{section.id}] {section.title}: {quote}")
            citations.append(
                {
                    "document_id": section.document_id,
                    "section_id": section.id,
                    "quote": quote,
                    "confidence": min(0.95, 0.45 + result.score / 10),
                }
            )
        context = "\n\n".join(snippets)
        answer = (
            f"Grounded answer to: {query}\n\n"
            f"Based on the selected source material, the most relevant evidence is:\n{context}\n\n"
            "This response is grounded in the cited section snippets and does not modify the original content."
        )
        return GroundedAnswer(
            query=query,
            answer=answer,
            citations=citations,
            model=self.openai.model,
            confidence=max((citation["confidence"] for citation in citations), default=0.3),
            trace=list(self._trace),
            used_broader_context=len(sections) > 1,
        )

    # ------------------------------------------------------------------
    # Controlled tools
    # ------------------------------------------------------------------
    def search_sections(self, query: str, scope: Scope, limit: int = 5, depth: int = 0) -> list[SearchResult]:
        self._check_tool_budget("search_sections")
        results = self.search.search_sections(query, scope, limit=limit)
        self._record_tool(
            "search_sections",
            {"query": query, "scope": scope.model_dump(), "limit": limit},
            f"{len(results)} section(s)",
            depth,
        )
        return results

    def read_section(self, section_id: str, depth: int = 0) -> Section | None:
        self._check_tool_budget("read_section")
        section = self.storage.get_section(section_id)
        self._record_tool("read_section", {"section_id": section_id}, section.title if section else "missing", depth)
        return section

    def read_figure(self, figure_id: str) -> dict | None:
        self._check_tool_budget("read_figure")
        figures = [figure for figure in self.storage.list_figures() if figure.id == figure_id]
        figure = figures[0] if figures else None
        self._record_tool("read_figure", {"figure_id": figure_id}, figure.caption if figure else "missing", 0)
        return figure.model_dump() if figure else None

    def read_equation(self, equation_id: str) -> dict | None:
        self._check_tool_budget("read_equation")
        equations = [equation for equation in self.storage.list_equations() if equation.id == equation_id]
        equation = equations[0] if equations else None
        self._record_tool("read_equation", {"equation_id": equation_id}, equation.mathjax if equation else "missing", 0)
        return equation.model_dump() if equation else None

    def list_document_sections(self, document_id: str) -> list[Section]:
        self._check_tool_budget("list_document_sections")
        sections = self.storage.list_sections(document_id)
        self._record_tool("list_document_sections", {"document_id": document_id}, f"{len(sections)} section(s)", 0)
        return sections

    def summarize_section(self, section_id: str) -> str:
        section = self.read_section(section_id)
        return section.ai_summary if section else ""

    def compare_sections(self, section_ids: list[str]) -> str:
        self._check_tool_budget("compare_sections")
        sections = [section for sid in section_ids if (section := self.storage.get_section(sid))]
        summary = "; ".join(f"{section.title}: {section.ai_summary[:120]}" for section in sections)
        self._record_tool("compare_sections", {"section_ids": section_ids}, summary, 0)
        return summary

    def create_subquestion(self, parent_question: str, results: list[SearchResult], depth: int = 0) -> list[str]:
        self._check_tool_budget("create_subquestion")
        targets = [result.title for result in results[:3]]
        subquestions = [f"{parent_question} — focus on {title}" for title in targets]
        self._record_tool(
            "create_subquestion",
            {"parent_question": parent_question, "targets": targets},
            f"{len(subquestions)} subquestion(s)",
            depth,
        )
        return subquestions

    def compose_grounded_answer(self, query: str, subanswers: list[GroundedAnswer], depth: int = 0) -> GroundedAnswer:
        self._check_tool_budget("compose_grounded_answer")
        citations: list[dict] = []
        body_parts: list[str] = []
        for subanswer in subanswers:
            body_parts.append(subanswer.answer)
            citations.extend(subanswer.citations)
        self._record_tool("compose_grounded_answer", {"subanswers": len(subanswers)}, f"{len(citations)} citation(s)", depth)
        return GroundedAnswer(
            query=query,
            answer=f"Recursive grounded answer to: {query}\n\n" + "\n\n---\n\n".join(body_parts),
            citations=citations,
            model=self.openai.model,
            confidence=max((item.get("confidence", 0.0) for item in citations), default=0.3),
            trace=list(self._trace),
            used_broader_context=True,
        )

    # ------------------------------------------------------------------
    # Limits and trace
    # ------------------------------------------------------------------
    def _check_tool_budget(self, tool_name: str) -> None:
        if self._tool_calls >= self.max_tool_calls:
            raise RuntimeError(f"RecursiveContextEngine tool limit reached before {tool_name}")
        self._tool_calls += 1

    def _record_tool(self, tool_name: str, inputs: dict, output_summary: str, depth: int) -> None:
        trace = ToolTrace(
            tool_name=tool_name,
            inputs={"run_id": self._run_id, **inputs},
            output_summary=output_summary[:500],
            depth=depth,
        )
        self._trace.append(trace)
        if self.trace_logging:
            self.storage.save_trace(trace)
