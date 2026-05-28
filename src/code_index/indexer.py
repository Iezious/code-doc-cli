"""Indexer pipeline — compose walker, plugins, embedding backend, storage.

Implements ``build(config, root, *, dry_run, verbose)``, the single entry
point that drives Phase 4's end-to-end flow: walk the project tree, dispatch
each file through its language plugin, batch chunk texts through the
embedding backend, and persist chunks / FTS5 / dense vectors / symbols /
edges / files via the Phase 1 storage helper. Plugin raises and per-file IO
errors skip + warn on stderr; infrastructure failures (storage / backend
init) raise :class:`code_index.errors.CodeIndexError`.

See ``docs/plans/004.walker-and-build/003.context.md`` for the column
mapping, the auto-rebuild SQL sequence, and the ``files`` upsert SQL.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from code_index.embeddings import EmbeddingBackend, from_config
from code_index.errors import write_log_stderr
from code_index.languages import Edge, Symbol, active_plugins
from code_index.languages.protocol import Language
from code_index.storage import open_index, set_meta
from code_index.walker import walk

if TYPE_CHECKING:
    from code_index.config import CodeIndexConfig
    from code_index.languages.registry import LanguageRegistry


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------


@dataclass
class IndexerResult:
    """Counts and elapsed time for a single ``build`` invocation.

    ``files_walked`` counts every :class:`WalkedFile` the walker yielded,
    including files whose plugin raised or whose IO failed. ``files_chunked``
    counts only files that were successfully processed end-to-end (and
    therefore got a ``files`` row in non-dry-run mode). ``chunks_chunked``
    counts every chunk the language plugins produced; ``chunks_inserted``
    is the subset actually written to the ``chunks`` table. Under
    ``dry_run=True`` the two diverge: ``chunks_chunked`` reflects the real
    chunker output while ``chunks_inserted`` stays zero because no rows are
    written.
    """

    files_walked: int
    files_chunked: int
    chunks_chunked: int
    chunks_inserted: int
    symbols_inserted: int
    edges_inserted: int
    seconds_elapsed: float


# ---------------------------------------------------------------------------
# Internal scratch records
# ---------------------------------------------------------------------------


@dataclass
class _PendingChunk:
    """Buffer entry: a chunk awaiting an embedding batch flush.

    Carries every value needed to insert the ``chunks`` / ``chunks_fts`` /
    ``embeddings`` rows once ``backend.encode`` returns the matching vector
    at the same buffer index. ``file_key`` ties the chunk to the file that
    produced it so the per-file ``files`` upsert can fire once every chunk
    has landed.
    """

    text: str
    path: str
    language: str
    project: str
    start_line: int
    end_line: int
    kind: str
    name: str | None
    scope: str | None
    file_key: int


@dataclass
class _PendingFile:
    """Per-file scratch: symbols, edges, and `files` row metadata.

    The file is "complete" once ``len(chunk_ids) == n_chunks``. At that
    point :func:`_finalize_file` writes the symbols, edges, and the
    ``files`` row. ``finalized`` is a one-shot latch.
    """

    rel_posix: str
    mtime: float
    size: int
    n_chunks: int
    symbols: list[Symbol]
    edges: list[Edge]
    started: float
    plugin_name: str
    chunk_ids: list[int] = field(default_factory=lambda: [])
    finalized: bool = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build(
    config: CodeIndexConfig,
    root: Path,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> IndexerResult:
    """Build the index for ``root`` using ``config``.

    Auto-rebuild: if the index already contains rows, the row data is
    silently cleared from chunks / chunks_fts / embeddings / symbols /
    edges / files, and the indexer-owned meta keys are reset, before
    insert. ``meta.schema_version`` is preserved.

    Writes to: ``chunks``, ``chunks_fts``, ``embeddings``, ``symbols``,
    ``edges``, ``files``, and the indexer-owned meta keys
    (``embed_model``, ``embed_dim``, ``embed_device``).

    Plugin raises and per-file IO errors: skip + warn on stderr, continue,
    do not raise.

    Infrastructure failures (storage open fails, backend init fails) raise
    :class:`code_index.errors.CodeIndexError` with the appropriate
    ``code`` / ``kind``.
    """
    started: float = time.monotonic()

    registry: LanguageRegistry = active_plugins(config)
    backend: EmbeddingBackend = from_config(config)

    root_abs: Path = Path(root).resolve()
    db_path: Path = root_abs / "docs" / ".helpers" / "index.sqlite"
    conn: sqlite3.Connection = open_index(db_path)

    try:
        if not dry_run:
            _auto_rebuild(conn)

        result = _run_pipeline(
            conn=conn,
            config=config,
            registry=registry,
            backend=backend,
            root_abs=root_abs,
            dry_run=dry_run,
            verbose=verbose,
        )

        if not dry_run:
            set_meta(conn, "embed_model", backend.name)
            set_meta(conn, "embed_dim", str(backend.dim))
            set_meta(conn, "embed_device", backend.device)
            conn.commit()
    finally:
        conn.close()

    elapsed: float = time.monotonic() - started
    result.seconds_elapsed = elapsed

    write_log_stderr(
        f"indexed {result.files_chunked} files, "
        f"{result.chunks_chunked} chunks in {elapsed:.1f}s"
    )
    return result


# ---------------------------------------------------------------------------
# Stat indirection
# ---------------------------------------------------------------------------


def _stat_file(path: Path) -> os.stat_result:
    """Stat ``path`` for the indexer's ``files`` upsert.

    Wrapped in its own function so tests can simulate per-file IO failures
    after the walker has already yielded the file (i.e. without breaking
    the walker's stat calls earlier in the pipeline).
    """
    return os.stat(path)


# ---------------------------------------------------------------------------
# Auto-rebuild
# ---------------------------------------------------------------------------


def _auto_rebuild(conn: sqlite3.Connection) -> None:
    """Clear row data from the six indexer-owned tables when ``chunks`` is non-empty.

    The probe is a single ``SELECT COUNT(*) FROM chunks`` per
    ``003.context.md``: Phase 1's migration creates all six tables together,
    so a non-empty ``chunks`` is sufficient evidence that prior build output
    needs to go. ``meta.schema_version`` and ``meta.code_index_version``
    are not touched; only the three indexer-owned keys
    (``embed_model``, ``embed_dim``, ``embed_device``) are reset.
    """
    row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
    count: int = int(row[0]) if row is not None else 0
    if count <= 0:
        return

    # Order matches the documented sequence; FK-less in Phase 1 but the
    # order is also the safe one if FKs are added later.
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM embeddings")
    conn.execute("DELETE FROM chunks_fts")
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM files")
    conn.execute(
        "DELETE FROM meta WHERE key IN ('embed_model', 'embed_dim', 'embed_device')"
    )


# ---------------------------------------------------------------------------
# Pipeline core
# ---------------------------------------------------------------------------


def _run_pipeline(
    *,
    conn: sqlite3.Connection,
    config: CodeIndexConfig,
    registry: LanguageRegistry,
    backend: EmbeddingBackend,
    root_abs: Path,
    dry_run: bool,
    verbose: bool,
) -> IndexerResult:
    """Walk + chunk + embed + insert. Caller fills ``seconds_elapsed``.

    Buffers chunk texts up to ``config.embed_batch_size`` before calling
    ``backend.encode`` and inserting rows. Symbols, edges, and the ``files``
    row are written once every chunk a file produced has been inserted.
    """
    counts = _Counters()
    batch_size: int = config.embed_batch_size
    buffer: list[_PendingChunk] = []
    pending_files: dict[int, _PendingFile] = {}
    next_file_key: int = 0

    for walked in walk(root_abs, config):
        counts.files_walked += 1

        plugin: Language | None = registry.for_extension(walked.extension)
        if plugin is None:
            # Walker should already filter to plugin-known extensions, but
            # defend in depth.
            continue

        rel_posix: str = walked.rel_path.as_posix()
        file_started: float = time.monotonic()

        # Plugin invocation: chunk / symbols / imports are wrapped in a
        # single try-block per `003.context.md`. Any raise on any of the
        # three skips the entire file.
        try:
            chunks = plugin.chunk(walked.path, walked.content)
            symbols = plugin.symbols(walked.path, walked.content)
            edges = plugin.imports(walked.path, walked.content)
        except Exception as exc:  # noqa: BLE001 — pinned skip-and-warn surface
            write_log_stderr(
                f"plugin {plugin.name} raised on {rel_posix}: {exc}"
            )
            continue

        # Per-file IO error: re-stat the file the walker opened so a
        # deletion-between-walk-and-now still produces a warning rather
        # than a hard raise. Stat is also where we collect mtime/size for
        # the `files` upsert. Indirected through ``_stat_file`` so tests
        # can simulate a mid-pipeline IO failure without patching the
        # walker's own stat calls.
        try:
            stat_result = _stat_file(walked.path)
        except OSError as exc:
            write_log_stderr(f"io error on {rel_posix}: {exc}")
            continue

        file_key: int = next_file_key
        next_file_key += 1
        pending_files[file_key] = _PendingFile(
            rel_posix=rel_posix,
            mtime=stat_result.st_mtime,
            size=stat_result.st_size,
            n_chunks=len(chunks),
            symbols=list(symbols),
            edges=list(edges),
            started=file_started,
            plugin_name=plugin.name,
        )
        counts.files_chunked += 1
        # ``chunks_chunked`` tracks chunker output regardless of dry-run,
        # giving the dry-run summary an observability signal beyond the
        # always-zero ``chunks_inserted``.
        counts.chunks_chunked += len(chunks)

        for chunk in chunks:
            buffer.append(
                _PendingChunk(
                    text=chunk.text,
                    path=rel_posix,
                    language=plugin.name,
                    project=config.project,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    kind=chunk.kind,
                    name=chunk.name,
                    scope=chunk.scope,
                    file_key=file_key,
                )
            )

        # Flush as many full batches as the buffer currently holds. A
        # single file may produce more than one batch's worth of chunks.
        while len(buffer) >= batch_size:
            head = buffer[:batch_size]
            del buffer[:batch_size]
            counts.chunks_inserted += _flush_batch(
                conn, head, backend, pending_files, dry_run
            )
            _finalize_completed_files(
                conn, pending_files, buffer, counts, dry_run, verbose
            )

        # A file with zero chunks (plugin returned an empty list) is
        # immediately "complete" — no buffer entries reference it. Settle
        # such files right away.
        if not chunks:
            _finalize_completed_files(
                conn, pending_files, buffer, counts, dry_run, verbose
            )

    # Final flush of any remaining buffer entries.
    if buffer:
        counts.chunks_inserted += _flush_batch(
            conn, buffer, backend, pending_files, dry_run
        )
        buffer.clear()
        _finalize_completed_files(
            conn, pending_files, buffer, counts, dry_run, verbose
        )

    return IndexerResult(
        files_walked=counts.files_walked,
        files_chunked=counts.files_chunked,
        chunks_chunked=counts.chunks_chunked,
        chunks_inserted=counts.chunks_inserted,
        symbols_inserted=counts.symbols_inserted,
        edges_inserted=counts.edges_inserted,
        seconds_elapsed=0.0,
    )


@dataclass
class _Counters:
    """Running totals threaded through the pipeline helpers."""

    files_walked: int = 0
    files_chunked: int = 0
    chunks_chunked: int = 0
    chunks_inserted: int = 0
    symbols_inserted: int = 0
    edges_inserted: int = 0


# ---------------------------------------------------------------------------
# Embedding flush
# ---------------------------------------------------------------------------


def _flush_batch(
    conn: sqlite3.Connection,
    batch: list[_PendingChunk],
    backend: EmbeddingBackend,
    pending_files: dict[int, _PendingFile],
    dry_run: bool,
) -> int:
    """Encode ``batch`` and insert rows into chunks / chunks_fts / embeddings.

    Under ``dry_run`` the encode call is skipped and no rows are written.
    Returns the number of chunks inserted (zero under dry-run).
    """
    if not batch:
        return 0
    if dry_run:
        # The dry-run path still needs to advance the per-file chunk-id
        # accounting so files with zero chunks are not the only "complete"
        # files in dry-run mode. We use a sentinel ``-1`` id; finalization
        # is also a no-op under dry-run so the value never reaches SQL.
        for pending_chunk in batch:
            pending_files[pending_chunk.file_key].chunk_ids.append(-1)
        return 0

    texts: list[str] = [pc.text for pc in batch]
    vectors: np.ndarray = backend.encode(texts)

    inserted: int = 0
    for index, pending_chunk in enumerate(batch):
        cursor = conn.execute(
            "INSERT INTO chunks("
            "  path, language, project, start_line, end_line, "
            "  kind, name, scope, content"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pending_chunk.path,
                pending_chunk.language,
                pending_chunk.project,
                pending_chunk.start_line,
                pending_chunk.end_line,
                pending_chunk.kind,
                pending_chunk.name,
                pending_chunk.scope,
                pending_chunk.text,
            ),
        )
        chunk_id_obj = cursor.lastrowid
        if chunk_id_obj is None:
            raise RuntimeError(
                "sqlite3 did not return lastrowid for chunks insert"
            )
        chunk_id: int = int(chunk_id_obj)

        conn.execute(
            "INSERT INTO chunks_fts(rowid, content, name, scope) "
            "VALUES (?, ?, ?, ?)",
            (
                chunk_id,
                pending_chunk.text,
                pending_chunk.name,
                pending_chunk.scope,
            ),
        )

        vector_bytes: bytes = (
            np.asarray(vectors[index], dtype=np.float32).tobytes()
        )
        conn.execute(
            "INSERT INTO embeddings(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, vector_bytes),
        )

        pending_files[pending_chunk.file_key].chunk_ids.append(chunk_id)
        inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Per-file finalization
# ---------------------------------------------------------------------------


def _finalize_completed_files(
    conn: sqlite3.Connection,
    pending_files: dict[int, _PendingFile],
    remaining_buffer: list[_PendingChunk],
    counts: _Counters,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Finalize every file whose chunks have all been inserted.

    A file is "complete" when ``len(chunk_ids) == n_chunks`` AND no entry
    for that ``file_key`` remains in ``remaining_buffer``. The second
    clause matters when a single file's chunks straddle a batch boundary.
    """
    still_pending: set[int] = {pc.file_key for pc in remaining_buffer}
    for file_key, pending in pending_files.items():
        if pending.finalized:
            continue
        if file_key in still_pending:
            continue
        if len(pending.chunk_ids) != pending.n_chunks:
            continue
        _finalize_file(conn, pending, counts, dry_run, verbose)


def _finalize_file(
    conn: sqlite3.Connection,
    pending: _PendingFile,
    counts: _Counters,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Insert this file's symbols + edges, then upsert its ``files`` row.

    Plugins emit symbols/edges with line numbers but no explicit chunk_id;
    the FK column on ``symbols.chunk_id`` / ``edges.src_chunk_id`` is filled
    by associating each symbol/edge with the file's first chunk_id when the
    plugin produced any chunks. Files with zero chunks still get a ``files``
    row but no symbol/edge rows (the FK would have nowhere to point).
    """
    pending.finalized = True

    if dry_run:
        if verbose:
            elapsed = time.monotonic() - pending.started
            write_log_stderr(
                f"indexed {pending.rel_posix} "
                f"({pending.n_chunks} chunks, {elapsed:.2f}s)"
            )
        return

    fk_chunk_id: int | None = (
        pending.chunk_ids[0] if pending.chunk_ids else None
    )

    if fk_chunk_id is not None:
        for symbol in pending.symbols:
            conn.execute(
                "INSERT INTO symbols(chunk_id, name, kind, line) "
                "VALUES (?, ?, ?, ?)",
                (fk_chunk_id, symbol.name, symbol.kind, symbol.line),
            )
            counts.symbols_inserted += 1

        for edge in pending.edges:
            meta_json: str | None = (
                json.dumps(edge.meta) if edge.meta is not None else None
            )
            conn.execute(
                "INSERT INTO edges(src_chunk_id, dst_name, kind, meta) "
                "VALUES (?, ?, ?, ?)",
                (fk_chunk_id, edge.target, edge.kind, meta_json),
            )
            counts.edges_inserted += 1

    conn.execute(
        "INSERT INTO files(path, mtime, size) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "  mtime = excluded.mtime, "
        "  size  = excluded.size",
        (pending.rel_posix, pending.mtime, pending.size),
    )

    if verbose:
        elapsed = time.monotonic() - pending.started
        write_log_stderr(
            f"indexed {pending.rel_posix} "
            f"({pending.n_chunks} chunks, {elapsed:.2f}s)"
        )


__all__ = ["IndexerResult", "build"]
