"""Pydantic schemas for Loci's source-preserving knowledge model."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Create a compact, prefixed UUID identifier."""

    return f"{prefix}_{uuid4().hex}"


SourceType = Literal["pdf", "markdown", "txt", "pasted"]
ArtifactType = Literal[
    "summary",
    "faq",
    "critique",
    "takeaways",
    "agent_message",
    "figure_description",
]
AnchorType = Literal["section", "text_span", "figure", "equation"]
Actor = Literal["user", "expert_agent", "critique_agent", "inexpert_agent"]


class GroundingReference(BaseModel):
    """Traceable source reference for an AI-generated item."""

    document_id: str | None = None
    section_id: str | None = None
    figure_id: str | None = None
    equation_id: str | None = None
    source_span: tuple[int, int] | None = None
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    quote: str | None = None
    confidence: float = 0.0
    note: str | None = None


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    source_type: SourceType
    source_path: str | None = None
    original_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Section(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sec"))
    document_id: str
    parent_id: str | None = None
    title: str
    level: int = 1
    order_index: int = 0
    page_start: int | None = None
    page_end: int | None = None
    verbatim_content: str
    ai_summary: str = ""
    source_char_start: int | None = None
    source_char_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Figure(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fig"))
    document_id: str
    section_id: str | None = None
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    crop_path: str
    caption: str | None = None
    ai_description: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Equation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("eq"))
    document_id: str
    section_id: str | None = None
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    source_text: str | None = None
    mathjax: str
    confidence: float | None = None
    render_status: str = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIArtifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    document_id: str
    section_id: str | None = None
    artifact_type: ArtifactType
    content: str
    grounding: list[dict[str, Any]] = Field(default_factory=list)
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=utc_now)
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscussionThread(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thread"))
    document_id: str
    section_id: str
    anchor_type: AnchorType = "section"
    anchor_id: str | None = None
    anchor_text: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscussionMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    thread_id: str
    actor: Actor
    content: str
    grounding: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SectionCandidate(BaseModel):
    title: str
    level: int = 1
    parent_title: str | None = None
    source_char_start: int
    source_char_end: int
    page_start: int | None = None
    page_end: int | None = None
    summary: str = ""
    confidence: float = 0.7


class FigureCandidate(BaseModel):
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    crop_path: str
    caption: str | None = None
    related_text: str | None = None
    confidence: float = 0.5


class EquationCandidate(BaseModel):
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    source_text: str | None = None
    mathjax: str
    related_text: str | None = None
    confidence: float = 0.5


class ParsedDocument(BaseModel):
    raw_text: str
    title: str | None = None
    sections: list[SectionCandidate] = Field(default_factory=list)
    figures: list[FigureCandidate] = Field(default_factory=list)
    equations: list[EquationCandidate] = Field(default_factory=list)
    page_spans: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    document: Document
    sections: list[Section] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    artifacts: list[AIArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    document_id: str | None = None
    section_id: str | None = None
    section_ids: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    section_id: str
    document_id: str
    title: str
    score: float
    snippet: str


class ToolTrace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trace"))
    run_id: str = Field(default_factory=lambda: new_id("run"))
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    timestamp: datetime = Field(default_factory=utc_now)
    depth: int = 0


class GroundedAnswer(BaseModel):
    query: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    model: str = "fallback-local"
    confidence: float = 0.0
    trace: list[ToolTrace] = Field(default_factory=list)
    used_broader_context: bool = False


class AgentRole(str, Enum):
    EXPERT = "expert_agent"
    CRITIQUE = "critique_agent"
    INEXPERT = "inexpert_agent"
