"""SQLite-backed persistence and immutable local file storage for Loci."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loci.models.database import connect, initialize_database
from loci.models.schemas import (
    AIArtifact,
    DiscussionMessage,
    DiscussionThread,
    Document,
    Equation,
    Figure,
    Section,
    ToolTrace,
    iso_now,
    new_id,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class StorageService:
    """Persistence facade for Loci domain models.

    The service deliberately treats sources as immutable files. New pasted text
    or uploaded files are written to fresh paths derived from their IDs and
    content hash; existing source paths are never overwritten.
    """

    def __init__(self, data_dir: str | Path | None = None, db_path: str | Path | None = None) -> None:
        package_data = Path(__file__).resolve().parents[1] / "data"
        self.data_dir = Path(data_dir) if data_dir is not None else package_data
        self.sources_dir = self.data_dir / "sources"
        self.crops_dir = self.data_dir / "crops"
        self.artifacts_dir = self.data_dir / "artifacts"
        for directory in (self.data_dir, self.sources_dir, self.crops_dir, self.artifacts_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path is not None else self.data_dir / "loci.sqlite"
        initialize_database(self.db_path)

    def connection(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # ------------------------------------------------------------------
    # Immutable source storage
    # ------------------------------------------------------------------
    def save_pasted_source(self, text: str, suffix: str = ".txt") -> tuple[str, str]:
        raw = text.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        path = self.sources_dir / f"{new_id('source')}_{digest[:12]}{suffix}"
        path.write_bytes(raw)
        return str(path), digest

    def save_uploaded_source(self, path: str | Path) -> tuple[str, str]:
        source = Path(path)
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        destination = self.sources_dir / f"{new_id('source')}_{digest[:12]}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        return str(destination), digest

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def create_document(
        self,
        title: str,
        source_type: str,
        source_path: str | None,
        original_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        document = Document(
            id=new_id("doc"),
            title=title,
            source_type=source_type,  # type: ignore[arg-type]
            source_path=source_path,
            original_hash=original_hash,
            created_at=iso_now(),
            metadata=metadata or {},
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO documents(id, title, source_type, source_path, original_hash, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.title,
                    document.source_type,
                    document.source_path,
                    document.original_hash,
                    document.created_at.isoformat(),
                    _json(document.metadata),
                ),
            )
        return document

    def list_documents(self) -> list[Document]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [self._row_to_document(row) for row in rows]

    def get_document(self, document_id: str) -> Document | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._row_to_document(row) if row else None

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            title=row["title"],
            source_type=row["source_type"],
            source_path=row["source_path"],
            original_hash=row["original_hash"],
            created_at=_dt(row["created_at"]),
            metadata=_loads(row["metadata"], {}),
        )

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def create_section(self, section: Section) -> Section:
        """Persist a section and return the stored model."""

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sections(
                  id, document_id, parent_id, title, level, order_index,
                  page_start, page_end, verbatim_content, ai_summary,
                  source_char_start, source_char_end, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    section.id,
                    section.document_id,
                    section.parent_id,
                    section.title,
                    section.level,
                    section.order_index,
                    section.page_start,
                    section.page_end,
                    section.verbatim_content,
                    section.ai_summary,
                    section.source_char_start,
                    section.source_char_end,
                    _json(section.metadata),
                ),
            )
            self._upsert_fts(conn, section)
        return section

    def update_section(self, section: Section) -> Section:
        """Update mutable derived section metadata without changing verbatim text identity."""

        with self.connection() as conn:
            conn.execute(
                """
                UPDATE sections
                SET parent_id = ?, title = ?, level = ?, order_index = ?,
                    page_start = ?, page_end = ?, verbatim_content = ?,
                    ai_summary = ?, source_char_start = ?, source_char_end = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    section.parent_id,
                    section.title,
                    section.level,
                    section.order_index,
                    section.page_start,
                    section.page_end,
                    section.verbatim_content,
                    section.ai_summary,
                    section.source_char_start,
                    section.source_char_end,
                    _json(section.metadata),
                    section.id,
                ),
            )
            self._upsert_fts(conn, section)
        return section

    def list_sections(self, document_id: str | None = None) -> list[Section]:
        query = "SELECT * FROM sections"
        params: tuple[Any, ...] = ()
        if document_id:
            query += " WHERE document_id = ?"
            params = (document_id,)
        query += " ORDER BY document_id, order_index, title"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_section(row) for row in rows]

    def update_section_summary(self, section_id: str, summary: str, metadata: dict[str, Any] | None = None) -> None:
        """Update only AI-owned section summary/metadata fields."""

        with self.connection() as conn:
            if metadata is None:
                conn.execute("UPDATE sections SET ai_summary = ? WHERE id = ?", (summary, section_id))
            else:
                conn.execute(
                    "UPDATE sections SET ai_summary = ?, metadata = ? WHERE id = ?",
                    (summary, _json(metadata), section_id),
                )
            section = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
            if section:
                self._upsert_fts(conn, self._row_to_section(section))

    def get_section(self, section_id: str) -> Section | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
        return self._row_to_section(row) if row else None

    def _upsert_fts(self, conn: sqlite3.Connection, section: Section) -> None:
        fts_enabled = conn.execute("SELECT value FROM app_metadata WHERE key = 'fts5_enabled'").fetchone()
        if not fts_enabled or fts_enabled["value"] != "true":
            return
        conn.execute(
            "INSERT OR REPLACE INTO section_fts(section_id, title, verbatim_content, ai_summary) VALUES (?, ?, ?, ?)",
            (section.id, section.title, section.verbatim_content, section.ai_summary),
        )

    def _row_to_section(self, row: sqlite3.Row) -> Section:
        return Section(
            id=row["id"],
            document_id=row["document_id"],
            parent_id=row["parent_id"],
            title=row["title"],
            level=row["level"],
            order_index=row["order_index"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            verbatim_content=row["verbatim_content"],
            ai_summary=row["ai_summary"],
            source_char_start=row["source_char_start"],
            source_char_end=row["source_char_end"],
            metadata=_loads(row["metadata"], {}),
        )

    # ------------------------------------------------------------------
    # Figures / equations
    # ------------------------------------------------------------------
    def create_figure(self, figure: Figure) -> Figure:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO figures(id, document_id, section_id, page_number, bbox, crop_path, caption, ai_description, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    figure.id,
                    figure.document_id,
                    figure.section_id,
                    figure.page_number,
                    _json(figure.bbox) if figure.bbox else None,
                    figure.crop_path,
                    figure.caption,
                    figure.ai_description,
                    figure.confidence,
                    _json(figure.metadata),
                ),
            )
        return figure

    def list_figures(self, document_id: str | None = None, section_id: str | None = None) -> list[Figure]:
        clauses: list[str] = []
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if section_id:
            clauses.append("section_id = ?")
            params.append(section_id)
        query = "SELECT * FROM figures"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY page_number, id"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_figure(row) for row in rows]

    def _row_to_figure(self, row: sqlite3.Row) -> Figure:
        return Figure(
            id=row["id"],
            document_id=row["document_id"],
            section_id=row["section_id"],
            page_number=row["page_number"],
            bbox=tuple(_loads(row["bbox"], [])) if row["bbox"] else None,  # type: ignore[arg-type]
            crop_path=row["crop_path"],
            caption=row["caption"],
            ai_description=row["ai_description"],
            confidence=row["confidence"],
            metadata=_loads(row["metadata"], {}),
        )

    def create_equation(self, equation: Equation) -> Equation:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO equations(id, document_id, section_id, page_number, bbox, source_text, mathjax, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    equation.id,
                    equation.document_id,
                    equation.section_id,
                    equation.page_number,
                    _json(equation.bbox) if equation.bbox else None,
                    equation.source_text,
                    equation.mathjax,
                    equation.confidence,
                    _json(equation.metadata),
                ),
            )
        return equation

    def list_equations(self, document_id: str | None = None, section_id: str | None = None) -> list[Equation]:
        clauses: list[str] = []
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if section_id:
            clauses.append("section_id = ?")
            params.append(section_id)
        query = "SELECT * FROM equations"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY page_number, id"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_equation(row) for row in rows]

    def _row_to_equation(self, row: sqlite3.Row) -> Equation:
        return Equation(
            id=row["id"],
            document_id=row["document_id"],
            section_id=row["section_id"],
            page_number=row["page_number"],
            bbox=tuple(_loads(row["bbox"], [])) if row["bbox"] else None,  # type: ignore[arg-type]
            source_text=row["source_text"],
            mathjax=row["mathjax"],
            confidence=row["confidence"],
            metadata=_loads(row["metadata"], {}),
        )

    # ------------------------------------------------------------------
    # AI artifacts
    # ------------------------------------------------------------------
    def create_artifact(self, artifact: AIArtifact) -> AIArtifact:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO ai_artifacts(
                  id, document_id, section_id, artifact_type, content, grounding,
                  model, prompt_version, created_at, confidence, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.document_id,
                    artifact.section_id,
                    artifact.artifact_type,
                    artifact.content,
                    _json(artifact.grounding),
                    artifact.model,
                    artifact.prompt_version,
                    artifact.created_at.isoformat(),
                    artifact.confidence,
                    _json(artifact.metadata),
                ),
            )
        return artifact

    def list_artifacts(
        self,
        document_id: str | None = None,
        section_id: str | None = None,
        artifact_type: str | None = None,
    ) -> list[AIArtifact]:
        clauses: list[str] = []
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if section_id is not None:
            clauses.append("section_id = ?")
            params.append(section_id)
        if artifact_type:
            clauses.append("artifact_type = ?")
            params.append(artifact_type)
        query = "SELECT * FROM ai_artifacts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def _row_to_artifact(self, row: sqlite3.Row) -> AIArtifact:
        return AIArtifact(
            id=row["id"],
            document_id=row["document_id"],
            section_id=row["section_id"],
            artifact_type=row["artifact_type"],
            content=row["content"],
            grounding=_loads(row["grounding"], []),
            model=row["model"],
            prompt_version=row["prompt_version"],
            created_at=_dt(row["created_at"]),
            confidence=row["confidence"],
            metadata=_loads(row["metadata"], {}),
        )

    # ------------------------------------------------------------------
    # Discussions
    # ------------------------------------------------------------------
    def get_or_create_root_thread(self, document_id: str, section_id: str) -> DiscussionThread:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM discussion_threads
                WHERE document_id = ? AND section_id = ? AND anchor_type = 'section' AND anchor_id IS NULL
                ORDER BY created_at LIMIT 1
                """,
                (document_id, section_id),
            ).fetchone()
        if row:
            return self._row_to_thread(row)
        thread = DiscussionThread(
            id=new_id("thread"),
            document_id=document_id,
            section_id=section_id,
            anchor_type="section",
            anchor_id=None,
            anchor_text=None,
            created_at=iso_now(),
            metadata={},
        )
        return self.create_thread(thread)

    def create_thread(self, thread: DiscussionThread) -> DiscussionThread:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO discussion_threads(id, document_id, section_id, anchor_type, anchor_id, anchor_text, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id,
                    thread.document_id,
                    thread.section_id,
                    thread.anchor_type,
                    thread.anchor_id,
                    thread.anchor_text,
                    thread.created_at.isoformat(),
                    _json(thread.metadata),
                ),
            )
        return thread

    def list_threads(self, section_id: str) -> list[DiscussionThread]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM discussion_threads WHERE section_id = ? ORDER BY created_at", (section_id,)
            ).fetchall()
        return [self._row_to_thread(row) for row in rows]

    def _row_to_thread(self, row: sqlite3.Row) -> DiscussionThread:
        return DiscussionThread(
            id=row["id"],
            document_id=row["document_id"],
            section_id=row["section_id"],
            anchor_type=row["anchor_type"],
            anchor_id=row["anchor_id"],
            anchor_text=row["anchor_text"],
            created_at=_dt(row["created_at"]),
            metadata=_loads(row["metadata"], {}),
        )

    def create_message(self, message: DiscussionMessage) -> DiscussionMessage:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO discussion_messages(id, thread_id, actor, content, grounding, created_at, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.thread_id,
                    message.actor,
                    message.content,
                    _json(message.grounding),
                    message.created_at.isoformat(),
                    message.confidence,
                    _json(message.metadata),
                ),
            )
        return message

    def list_messages(self, thread_id: str) -> list[DiscussionMessage]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM discussion_messages WHERE thread_id = ? ORDER BY created_at", (thread_id,)
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def _row_to_message(self, row: sqlite3.Row) -> DiscussionMessage:
        return DiscussionMessage(
            id=row["id"],
            thread_id=row["thread_id"],
            actor=row["actor"],
            content=row["content"],
            grounding=_loads(row["grounding"], []),
            created_at=_dt(row["created_at"]),
            confidence=row["confidence"],
            metadata=_loads(row["metadata"], {}),
        )

    # ------------------------------------------------------------------
    # Embeddings and traces
    # ------------------------------------------------------------------
    def save_embedding(
        self,
        owner_type: str,
        owner_id: str,
        text_hash: str,
        model: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
        embedding_type: str = "content",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO embeddings(id, owner_type, owner_id, text_hash, embedding_type, model, vector, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("emb"),
                    owner_type,
                    owner_id,
                    text_hash,
                    embedding_type,
                    model,
                    _json(vector),
                    iso_now().isoformat(),
                    _json(metadata or {}),
                ),
            )

    def list_embeddings(self, owner_type: str | None = None, embedding_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM embeddings"
        clauses: list[str] = []
        params: list[Any] = []
        if owner_type:
            clauses.append("owner_type = ?")
            params.append(owner_type)
        if embedding_type:
            clauses.append("embedding_type = ?")
            params.append(embedding_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) | {"vector": _loads(row["vector"], []), "metadata": _loads(row["metadata"], {})} for row in rows]

    def save_trace(self, trace: ToolTrace) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO rce_traces(id, run_id, tool_name, input, output_summary, timestamp, depth, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("trace"),
                    trace.inputs.get("run_id", "manual"),
                    trace.tool_name,
                    _json(trace.inputs),
                    trace.output_summary,
                    trace.timestamp.isoformat(),
                    trace.depth,
                    "{}",
                ),
            )

    def list_traces(self, run_id: str | None = None) -> list[ToolTrace]:
        query = "SELECT * FROM rce_traces"
        params: tuple[Any, ...] = ()
        if run_id:
            query += " WHERE run_id = ?"
            params = (run_id,)
        query += " ORDER BY timestamp"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ToolTrace(
                tool_name=row["tool_name"],
                inputs=_loads(row["input"], {}),
                output_summary=row["output_summary"],
                timestamp=_dt(row["timestamp"]),
                depth=row["depth"],
            )
            for row in rows
        ]

