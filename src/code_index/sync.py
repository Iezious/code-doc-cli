"""Incremental sync engine for ``code_index index sync``.

Phase 6, step 001. Walks the project root, joins each walked file against
the ``files`` table by ``path``, and dispatches to per-file insert /
re-insert / no-op / delete based on the mtime+size comparison documented in
``docs/plans/006.sync-symbols-graph/context.md`` ("Sync algorithm spec").

Per-file insert is reimplemented locally rather than extracting a private
helper out of :mod:`code_index.indexer` (option 2 in
``001.context.md``). The column mapping is the one pinned by Phase 4's
``003.context.md`` — chunks / chunks_fts / embeddings / symbols / edges /
files — so adding new rows here produces the same shape as
:func:`code_index.indexer.build`.

The :func:`delete_file_rows` helper is owned by this module (not by
:mod:`code_index.indexer`) per the Phase 6 plan; it is the one shared
primitive between sync's "changed" and "removed" branches and the SQL
sequence it runs is the contract the rest of Phase 6 reads off.

Plugin raise and per-file IO error are treated the same as in Phase 4:
skip + stderr warning + continue. On a *changed* file this leaves the
prior rows alone, because :func:`delete_file_rows` only runs after the
plugin has successfully produced chunks/symbols/edges.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from code_index import embeddings
from code_index.embeddings import EmbeddingBackend
from code_index.errors import write_log_stderr
from code_index.languages import Edge, Symbol, active_plugins
from code_index.languages.protocol import Language
from code_index.walker import WalkedFile, walk

if TYPE_CHECKING:
    from code_index.config import CodeIndexConfig
    from code_index.languages.registry import LanguageRegistry


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Counts and elapsed time for one :func:`sync` invocation.

    ``files_added`` / ``files_changed`` / ``files_unchanged`` / ``files_removed``
    partition the union of (walked files, files-table rows). A file that the
    plugin/IO layer skipped is counted neither as added nor changed; it stays
    unchanged from the index's point of view because no rows were touched.
    ``chunks_inserted_total`` sums all chunk inserts across added and changed
    files (re-inserts after delete count as inserts).
    """

    files_added: int
    files_changed: int
    files_unchanged: int
    files_removed: int
    chunks_inserted_total: int
    seconds_elapsed: float


# ---------------------------------------------------------------------------
# Per-file delete helper
# ---------------------------------------------------------------------------


def delete_file_rows(conn: sqlite3.Connection, path: str) -> None:
    """Delete every row owned by ``path`` from the six row-data tables.

    The SQL sequence matches the one pinned in
    ``docs/plans/006.sync-symbols-graph/context.md``: dependent tables
    (edges, symbols, embeddings, chunks_fts) first — joined to chunks via
    the ``id`` IN (...) subquery — then chunks itself, then the ``files``
    row. The whole sequence runs on ``conn`` without an explicit
    ``BEGIN`` / ``COMMIT``; the caller decides transaction boundaries.
    """
    # Edges and symbols hang off chunks via FK-shaped int columns.
    conn.execute(
        "DELETE FROM edges WHERE src_chunk_id IN "
        "(SELECT id FROM chunks WHERE path = ?)",
        (path,),
    )
    conn.execute(
        "DELETE FROM symbols WHERE chunk_id IN "
        "(SELECT id FROM chunks WHERE path = ?)",
        (path,),
    )
    # Embeddings is a vec0 virtual table keyed by chunk_id.
    conn.execute(
        "DELETE FROM embeddings WHERE chunk_id IN "
        "(SELECT id FROM chunks WHERE path = ?)",
        (path,),
    )
    # chunks_fts is a contentless FTS5 mirror; rowid == chunks.id.
    conn.execute(
        "DELETE FROM chunks_fts WHERE rowid IN "
        "(SELECT id FROM chunks WHERE path = ?)",
        (path,),
    )
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------


def sync(
    config: CodeIndexConfig,
    root: Path,
    *,
    verbose: bool = False,
) -> SyncResult:
    """Incremental update against an existing index.

    Walks ``root`` via :func:`code_index.walker.walk`, reads the ``files``
    table into an in-memory map, and dispatches each walked file to the
    "added" / "changed" / "unchanged" branch. After the walk, any path in
    the files map that the walker did not produce is treated as removed
    and its rows are deleted via :func:`delete_file_rows`.

    Assumes the standard Phase 6 pre-flight check (index exists, embed
    model and dim match the configured backend) has already run in the
    CLI layer — this function does not re-validate.
    """
    started: float = time.monotonic()

    registry: LanguageRegistry = active_plugins(config)
    # Resolve ``from_config`` through the package each call so monkeypatching
    # :mod:`code_index.embeddings` is sufficient — the sync module does not
    # bind the factory at import time. (See bug fix to feature 006 step 005.)
    backend: EmbeddingBackend = embeddings.from_config(config)

    root_abs: Path = Path(root).resolve()
    db_path: Path = root_abs / "docs" / ".helpers" / "index.sqlite"
    # Pre-flight has already opened+verified the index, but the engine owns
    # its own connection for the sync transaction. ``open_index`` with
    # ``create_if_missing=True`` is fine: the pre-flight ensured the file
    # exists, so this opens an existing DB (no migrations run).
    from code_index.storage import open_index

    conn: sqlite3.Connection = open_index(db_path)

    files_added: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    chunks_inserted_total: int = 0

    try:
        # 1. Read the current files table into a {path: (mtime, size)} map.
        files_map: dict[str, tuple[float, int]] = {}
        for row in conn.execute("SELECT path, mtime, size FROM files"):
            files_map[str(row[0])] = (float(row[1]), int(row[2]))

        # 2. Walk and classify. Keep the set of walked paths so step 3 can
        #    delete the leftover files-table rows.
        walked_paths: set[str] = set()

        for walked in walk(root_abs, config):
            plugin: Language | None = registry.for_extension(walked.extension)
            if plugin is None:
                # Walker already filters to plugin-known extensions, but
                # defend in depth.
                continue

            rel_posix: str = walked.rel_path.as_posix()
            walked_paths.add(rel_posix)

            existing: tuple[float, int] | None = files_map.get(rel_posix)
            if existing is not None:
                # Probe current mtime+size; "unchanged" is the cheap branch.
                try:
                    stat_now = os.stat(walked.path)
                except OSError as exc:
                    write_log_stderr(
                        f"io error on {rel_posix}: {exc}"
                    )
                    continue
                if (
                    stat_now.st_mtime == existing[0]
                    and stat_now.st_size == existing[1]
                ):
                    files_unchanged += 1
                    if verbose:
                        write_log_stderr(
                            f"synced {rel_posix} (unchanged)"
                        )
                    continue

                # Changed file: re-insert. Delete is deferred until after
                # the plugin succeeds (so a plugin raise does not orphan
                # the file).
                inserted = _insert_one_file(
                    conn=conn,
                    walked=walked,
                    plugin=plugin,
                    backend=backend,
                    config=config,
                    delete_first=True,
                )
                if inserted is None:
                    # Plugin / IO error already warned; leave old rows alone
                    # and count the file as unchanged from the index's view.
                    files_unchanged += 1
                    continue
                files_changed += 1
                chunks_inserted_total += inserted
                if verbose:
                    write_log_stderr(
                        f"synced {rel_posix} (changed, {inserted} chunks)"
                    )
                continue

            # New file (not in files_map).
            inserted = _insert_one_file(
                conn=conn,
                walked=walked,
                plugin=plugin,
                backend=backend,
                config=config,
                delete_first=False,
            )
            if inserted is None:
                # Plugin / IO error already warned; nothing to count.
                continue
            files_added += 1
            chunks_inserted_total += inserted
            if verbose:
                write_log_stderr(
                    f"synced {rel_posix} (added, {inserted} chunks)"
                )

        # 3. Removed files: anything in files_map the walker did not produce.
        for path in files_map:
            if path in walked_paths:
                continue
            delete_file_rows(conn, path)
            files_removed += 1
            if verbose:
                write_log_stderr(f"removed {path}")

        conn.commit()
    finally:
        conn.close()

    elapsed: float = time.monotonic() - started
    result = SyncResult(
        files_added=files_added,
        files_changed=files_changed,
        files_unchanged=files_unchanged,
        files_removed=files_removed,
        chunks_inserted_total=chunks_inserted_total,
        seconds_elapsed=elapsed,
    )

    write_log_stderr(
        f"synced: +{files_added} ~{files_changed} ={files_unchanged} "
        f"-{files_removed} ({chunks_inserted_total} chunks) "
        f"in {elapsed:.2f}s"
    )
    return result


# ---------------------------------------------------------------------------
# Per-file insert (added or changed branches share this)
# ---------------------------------------------------------------------------


def _insert_one_file(
    *,
    conn: sqlite3.Connection,
    walked: WalkedFile,
    plugin: Language,
    backend: EmbeddingBackend,
    config: CodeIndexConfig,
    delete_first: bool,
) -> int | None:
    """Insert one file's worth of rows; return the chunk count, or ``None``.

    ``None`` means the plugin raised or the per-file IO stat failed — the
    standard Phase 4 skip-and-warn surface. When ``delete_first`` is
    ``True`` (the "changed" branch), the old rows are dropped *after* the
    plugin has produced chunks/symbols/edges and *before* the new rows are
    written. This ordering matters: if the plugin raises mid-way the file
    is left with its old rows intact, matching the per-step context's
    "skip on changed leaves old rows alone" contract.
    """
    rel_posix: str = walked.rel_path.as_posix()

    # Plugin invocation: all three calls in one try-block per Phase 4.
    try:
        chunks = plugin.chunk(walked.path, walked.content)
        symbols = plugin.symbols(walked.path, walked.content)
        edges = plugin.imports(walked.path, walked.content)
    except Exception as exc:  # noqa: BLE001 — pinned skip-and-warn surface
        write_log_stderr(
            f"plugin {plugin.name} raised on {rel_posix}: {exc}"
        )
        return None

    # Per-file IO stat — drives the ``files`` row's mtime/size.
    try:
        stat_result = _stat_file(walked.path)
    except OSError as exc:
        write_log_stderr(f"io error on {rel_posix}: {exc}")
        return None

    # All inputs succeeded; safe to drop the old rows.
    if delete_first:
        delete_file_rows(conn, rel_posix)

    # Encode every chunk in one batch — for one-file sync the per-file
    # batch is the natural granularity, and configurable batch sizes apply
    # to multi-file builds (Phase 4) rather than per-file sync.
    chunk_ids: list[int] = []
    if chunks:
        texts: list[str] = [chunk.text for chunk in chunks]
        vectors: np.ndarray = backend.encode(texts)
        for index, chunk in enumerate(chunks):
            cursor = conn.execute(
                "INSERT INTO chunks("
                "  path, language, project, start_line, end_line, "
                "  kind, name, scope, content"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rel_posix,
                    plugin.name,
                    config.project,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.kind,
                    chunk.name,
                    chunk.scope,
                    chunk.text,
                ),
            )
            chunk_id_obj = cursor.lastrowid
            if chunk_id_obj is None:
                raise RuntimeError(
                    "sqlite3 did not return lastrowid for chunks insert"
                )
            chunk_id: int = int(chunk_id_obj)
            chunk_ids.append(chunk_id)

            # chunks_fts is contentless; Phase 1 did not install triggers,
            # so the indexer writes the mirror row explicitly. We do the
            # same here.
            conn.execute(
                "INSERT INTO chunks_fts(rowid, content, name, scope) "
                "VALUES (?, ?, ?, ?)",
                (chunk_id, chunk.text, chunk.name, chunk.scope),
            )

            vector_bytes: bytes = (
                np.asarray(vectors[index], dtype=np.float32).tobytes()
            )
            conn.execute(
                "INSERT INTO embeddings(chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, vector_bytes),
            )

    # Symbols and edges hang off the file's first chunk_id, matching the
    # Phase 4 indexer's contract. A file with zero chunks still gets a
    # ``files`` row but no symbol/edge rows.
    fk_chunk_id: int | None = chunk_ids[0] if chunk_ids else None
    if fk_chunk_id is not None:
        _insert_symbols(conn, fk_chunk_id, symbols)
        _insert_edges(conn, fk_chunk_id, edges)

    # Upsert the ``files`` row last. mtime/size come from the stat call
    # made before any inserts so the recorded values match the bytes that
    # produced these chunks.
    conn.execute(
        "INSERT INTO files(path, mtime, size) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "  mtime = excluded.mtime, "
        "  size  = excluded.size",
        (rel_posix, stat_result.st_mtime, stat_result.st_size),
    )

    return len(chunk_ids)


def _insert_symbols(
    conn: sqlite3.Connection, chunk_id: int, symbols: list[Symbol]
) -> None:
    """Insert one row per :class:`Symbol` against ``chunk_id``."""
    for symbol in symbols:
        conn.execute(
            "INSERT INTO symbols(chunk_id, name, kind, line) "
            "VALUES (?, ?, ?, ?)",
            (chunk_id, symbol.name, symbol.kind, symbol.line),
        )


def _insert_edges(
    conn: sqlite3.Connection, chunk_id: int, edges: list[Edge]
) -> None:
    """Insert one row per :class:`Edge` against ``chunk_id``.

    ``meta`` is JSON-encoded when present, ``None`` otherwise — matching
    the Phase 4 indexer's column mapping.
    """
    for edge in edges:
        meta_json: str | None = (
            json.dumps(edge.meta) if edge.meta is not None else None
        )
        conn.execute(
            "INSERT INTO edges(src_chunk_id, dst_name, kind, meta) "
            "VALUES (?, ?, ?, ?)",
            (chunk_id, edge.target, edge.kind, meta_json),
        )


def _stat_file(path: Path) -> os.stat_result:
    """Stat ``path`` for the sync engine's per-file metadata.

    Wrapped in a module-level function so tests can simulate a stat
    failure mid-pipeline (mirroring :func:`code_index.indexer._stat_file`).
    """
    return os.stat(path)


__all__ = ["SyncResult", "delete_file_rows", "sync"]
