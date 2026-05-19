"""Migration 0 -> 1: create the full Phase 1 schema.

Mirrors the schema sketch in ``docs/architecture/storage.md`` plus the
2026-05-19 ``files`` table addition. Six tables (``meta``, ``files``,
``chunks``, ``chunks_fts`` FTS5, ``embeddings`` vec0, ``symbols``, ``edges``)
and five named indices. The ``embeddings`` virtual table requires a concrete
dim; Phase 1 uses 768 (fastembed Jina v2 base code dim, the project default
embedding backend per ``docs/architecture/embeddings.md``). Phase 2 owns any
revision to that choice.
"""

from __future__ import annotations

import sqlite3

import code_index

from_version: str = "0"
to_version: str = "1"

EMBEDDING_DIM: int = 768

_DDL_STATEMENTS: tuple[str, ...] = (
    # meta — schema_version, code_index_version, embed_model, embed_dim, ...
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    # files — per-file sync state populated by the Phase 4 indexer.
    """
    CREATE TABLE IF NOT EXISTS files (
        path  TEXT PRIMARY KEY,
        mtime REAL,
        size  INTEGER
    )
    """,
    # chunks — primary content table.
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id         INTEGER PRIMARY KEY,
        path       TEXT,
        language   TEXT,
        project    TEXT,
        start_line INTEGER,
        end_line   INTEGER,
        kind       TEXT,
        name       TEXT,
        scope      TEXT,
        content    TEXT
    )
    """,
    # FTS5 contentless-mirror over chunks(content, name, scope).
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        content,
        name,
        scope,
        content='chunks',
        content_rowid='id'
    )
    """,
    # sqlite-vec dense store. Dim pinned at table creation time.
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(
        chunk_id INTEGER PRIMARY KEY,
        embedding FLOAT[{EMBEDDING_DIM}]
    )
    """,
    # symbols — def/ref rows used for graph queries.
    """
    CREATE TABLE IF NOT EXISTS symbols (
        id       INTEGER PRIMARY KEY,
        chunk_id INTEGER,
        name     TEXT,
        kind     TEXT,
        line     INTEGER
    )
    """,
    # edges — unresolved free-form dst_name strings; resolved at query time.
    """
    CREATE TABLE IF NOT EXISTS edges (
        src_chunk_id INTEGER,
        dst_name     TEXT,
        kind         TEXT,
        meta         TEXT
    )
    """,
    # Indices named in storage.md "Schema sketch".
    "CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_language ON chunks(language)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)",
    "CREATE INDEX IF NOT EXISTS idx_edges_dst_name ON edges(dst_name)",
    "CREATE INDEX IF NOT EXISTS idx_edges_src_chunk_id ON edges(src_chunk_id)",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create every table, virtual table, and index for schema v1.

    Also writes ``meta.code_index_version`` to ``code_index.__version__``.
    The runner is responsible for writing ``meta.schema_version = '1'`` after
    this returns (so both writes share the same migration transaction).
    """
    for stmt in _DDL_STATEMENTS:
        conn.execute(stmt)

    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('code_index_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (code_index.__version__,),
    )
