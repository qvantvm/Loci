from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_path TEXT,
    original_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    level INTEGER NOT NULL,
    order_index INTEGER NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    verbatim_content TEXT NOT NULL,
    ai_summary TEXT NOT NULL DEFAULT '',
    source_char_start INTEGER,
    source_char_end INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS figures (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
    page_number INTEGER,
    bbox TEXT,
    crop_path TEXT NOT NULL,
    caption TEXT,
    ai_description TEXT,
    confidence REAL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS equations (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
    page_number INTEGER,
    bbox TEXT,
    source_text TEXT,
    mathjax TEXT NOT NULL,
    confidence REAL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ai_artifacts (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id TEXT REFERENCES sections(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    content TEXT NOT NULL,
    grounding TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confidence REAL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS discussion_threads (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    anchor_type TEXT NOT NULL,
    anchor_id TEXT,
    anchor_text TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS discussion_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES discussion_threads(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    content TEXT NOT NULL,
    grounding TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    confidence REAL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    text_hash TEXT,
    embedding_type TEXT NOT NULL DEFAULT 'content',
    vector TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rce_traces (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input TEXT NOT NULL DEFAULT '{}',
    output_summary TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    depth INTEGER NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id, order_index);
CREATE INDEX IF NOT EXISTS idx_sections_parent ON sections(parent_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_document ON ai_artifacts(document_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON discussion_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_traces_run ON rce_traces(run_id, timestamp);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: str | Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS section_fts USING fts5(section_id UNINDEXED, title, verbatim_content, ai_summary)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('fts5_enabled', 'true')"
            )
        except sqlite3.OperationalError:
            # Some embedded SQLite builds omit FTS5. SearchService has a lexical fallback.
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('fts5_enabled', 'false')"
            )
        conn.commit()
    finally:
        conn.close()
