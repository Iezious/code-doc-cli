"""Tests for the sync engine.

Exercises :func:`code_index.sync.sync` directly with mocked plugins and a
mocked embedding backend, following the Phase 4 ``test_indexer_pipeline``
pattern. Pinned scenarios from
``docs/plans/006.sync-symbols-graph/001.sync-engine.md`` "Tests":

1. No-op sync.
2. New file.
3. Changed file (mtime).
4. Changed file (size only).
5. Removed file.
6. Mixed (one added, one changed, one removed, two unchanged).
7. ``delete_file_rows`` happy path.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from code_index import embeddings, indexer, walker
from code_index import sync as sync_module
from code_index.config import CodeIndexConfig
from code_index.languages import Chunk, Edge, Symbol
from code_index.languages.registry import LanguageRegistry
from code_index.storage import open_index

_EMBED_DIM: int = 768


# ---------------------------------------------------------------------------
# Fake plugin / backend doubles (mirrors test_indexer_pipeline.py)
# ---------------------------------------------------------------------------


@dataclass
class FakePlugin:
    """Test double exposing the structural :class:`Language` Protocol."""

    name: str
    extensions: tuple[str, ...]
    chunks_by_path: dict[str, list[Chunk]]
    symbols_by_path: dict[str, list[Symbol]]
    edges_by_path: dict[str, list[Edge]]

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        del content
        return list(self.chunks_by_path.get(path.name, []))

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        del content
        return list(self.symbols_by_path.get(path.name, []))

    def imports(self, path: Path, content: str) -> list[Edge]:
        del content
        return list(self.edges_by_path.get(path.name, []))


class FakeBackend:
    """Deterministic embedding backend; vectors are content-derived."""

    name: str = "fake:tiny"
    dim: int = _EMBED_DIM

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            out[i, 0] = float(len(text))
            out[i, 1] = float(i)
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(*, embed_batch_size: int = 32) -> CodeIndexConfig:
    return CodeIndexConfig(
        version=">=0.1,<1.0",
        project="sync-test",
        roots=["."],
        ignores=[],
        languages=["python"],
        extra_languages=[],
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=embed_batch_size,
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    plugins: list[FakePlugin],
    backend: FakeBackend,
) -> None:
    """Wire fake plugins + backend into both the indexer and the sync engine."""
    registry = LanguageRegistry(plugins)  # type: ignore[arg-type]
    # Indexer uses these for the initial build.
    monkeypatch.setattr(indexer, "active_plugins", lambda config: registry)
    monkeypatch.setattr(indexer, "from_config", lambda config: backend)
    # Walker also calls active_plugins to derive the extension filter.
    monkeypatch.setattr(walker, "active_plugins", lambda config: registry)
    # Sync engine uses these on every invocation.
    monkeypatch.setattr(sync_module, "active_plugins", lambda config: registry)
    # The sync engine resolves embeddings via ``embeddings.from_config`` at
    # call time (it does not bind ``from_config`` into its own namespace at
    # import time), so patching the package symbol is sufficient.
    monkeypatch.setattr(embeddings, "from_config", lambda config: backend)


def _make_plugin(file_map: dict[str, tuple[str, str | None]]) -> FakePlugin:
    """Build a python-like plugin where each file produces one named chunk.

    ``file_map`` maps ``"name.py"`` -> ``(text, symbol_name)``. If
    ``symbol_name`` is ``None`` the file emits a chunk with no symbols/edges.
    """
    chunks_by_path: dict[str, list[Chunk]] = {}
    symbols_by_path: dict[str, list[Symbol]] = {}
    edges_by_path: dict[str, list[Edge]] = {}
    for name, (text, symbol_name) in file_map.items():
        chunks_by_path[name] = [
            Chunk(
                start_line=1,
                end_line=1,
                kind="function",
                name=symbol_name,
                scope=None,
                text=text,
            )
        ]
        if symbol_name is not None:
            symbols_by_path[name] = [
                Symbol(name=symbol_name, kind="def", line=1)
            ]
            edges_by_path[name] = [
                Edge(target=f"{symbol_name}_dep", kind="import", line=1, meta=None)
            ]
    return FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path=chunks_by_path,
        symbols_by_path=symbols_by_path,
        edges_by_path=edges_by_path,
    )


def _db_conn(tmp_path: Path) -> sqlite3.Connection:
    return open_index(tmp_path / "docs" / ".helpers" / "index.sqlite")


def _initial_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin: FakePlugin,
) -> CodeIndexConfig:
    """Run the indexer once against ``tmp_path``; return the config used."""
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, [plugin], backend)
    config = _make_config()
    indexer.build(config, tmp_path)
    return config


def _chunk_ids_by_path(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """Return ``{path: [chunk.id, ...]}`` for the whole ``chunks`` table."""
    out: dict[str, list[int]] = {}
    for row in conn.execute("SELECT path, id FROM chunks ORDER BY id"):
        out.setdefault(str(row[0]), []).append(int(row[1]))
    return out


# ---------------------------------------------------------------------------
# 1. No-op sync
# ---------------------------------------------------------------------------


def test_sync_noop_keeps_chunk_ids_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta", encoding="utf-8")
    plugin = _make_plugin(
        {"a.py": ("alpha", "alpha"), "b.py": ("beta", "beta")}
    )
    config = _initial_build(tmp_path, monkeypatch, plugin)

    conn = _db_conn(tmp_path)
    try:
        before = _chunk_ids_by_path(conn)
    finally:
        conn.close()

    result = sync_module.sync(config, tmp_path)

    assert result.files_added == 0
    assert result.files_changed == 0
    assert result.files_removed == 0
    assert result.files_unchanged == 2
    assert result.chunks_inserted_total == 0

    conn = _db_conn(tmp_path)
    try:
        after = _chunk_ids_by_path(conn)
    finally:
        conn.close()
    assert after == before, (before, after)


# ---------------------------------------------------------------------------
# 2. New file
# ---------------------------------------------------------------------------


def test_sync_detects_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    plugin = _make_plugin({"a.py": ("alpha", "alpha")})
    config = _initial_build(tmp_path, monkeypatch, plugin)

    # Add a second file and teach the plugin about it.
    new_path = tmp_path / "b.py"
    new_path.write_text("beta", encoding="utf-8")
    plugin.chunks_by_path["b.py"] = [
        Chunk(
            start_line=1,
            end_line=1,
            kind="function",
            name="beta",
            scope=None,
            text="beta",
        )
    ]
    plugin.symbols_by_path["b.py"] = [Symbol(name="beta", kind="def", line=1)]
    plugin.edges_by_path["b.py"] = [
        Edge(target="beta_dep", kind="import", line=1, meta=None)
    ]

    result = sync_module.sync(config, tmp_path)

    assert result.files_added == 1
    assert result.files_changed == 0
    assert result.files_removed == 0
    assert result.files_unchanged == 1
    assert result.chunks_inserted_total == 1

    conn = _db_conn(tmp_path)
    try:
        # Rows present in every row-data table for the new file.
        for table, where in (
            ("chunks", "path = 'b.py'"),
            ("symbols", "chunk_id IN (SELECT id FROM chunks WHERE path = 'b.py')"),
            ("edges", "src_chunk_id IN (SELECT id FROM chunks WHERE path = 'b.py')"),
            ("embeddings", "chunk_id IN (SELECT id FROM chunks WHERE path = 'b.py')"),
            ("chunks_fts", "rowid IN (SELECT id FROM chunks WHERE path = 'b.py')"),
            ("files", "path = 'b.py'"),
        ):
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}"
            ).fetchone()
            assert row is not None and row[0] >= 1, (table, row)

        files_row = conn.execute(
            "SELECT mtime, size FROM files WHERE path = 'b.py'"
        ).fetchone()
        assert files_row is not None
        st = os.stat(new_path)
        assert files_row[0] == pytest.approx(st.st_mtime)
        assert files_row[1] == st.st_size
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Changed file (mtime advanced by rewrite)
# ---------------------------------------------------------------------------


def test_sync_detects_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta", encoding="utf-8")
    plugin = _make_plugin(
        {"a.py": ("alpha", "alpha"), "b.py": ("beta", "beta")}
    )
    config = _initial_build(tmp_path, monkeypatch, plugin)

    conn = _db_conn(tmp_path)
    try:
        before = _chunk_ids_by_path(conn)
    finally:
        conn.close()

    # Rewrite a.py to a longer body and bump mtime two seconds into the
    # future so the change is detectable on every FS we test on (FAT32's
    # 2-second mtime resolution is the worst case).
    new_text = "alpha_v2_longer"
    target = tmp_path / "a.py"
    target.write_text(new_text, encoding="utf-8")
    new_mtime = os.stat(target).st_mtime + 2.0
    os.utime(target, (new_mtime, new_mtime))

    # Teach the plugin to return a new chunk for the rewritten file.
    plugin.chunks_by_path["a.py"] = [
        Chunk(
            start_line=1,
            end_line=1,
            kind="function",
            name="alpha2",
            scope=None,
            text=new_text,
        )
    ]
    plugin.symbols_by_path["a.py"] = [Symbol(name="alpha2", kind="def", line=1)]

    result = sync_module.sync(config, tmp_path)

    assert result.files_changed == 1
    assert result.files_added == 0
    assert result.files_removed == 0
    assert result.files_unchanged == 1
    assert result.chunks_inserted_total == 1

    conn = _db_conn(tmp_path)
    try:
        after = _chunk_ids_by_path(conn)
        # Old chunk_ids for a.py are gone.
        assert set(after["a.py"]).isdisjoint(set(before["a.py"]))
        # b.py untouched.
        assert after["b.py"] == before["b.py"]
        # FTS5 stayed in sync — no stale rowids pointing at gone chunks.
        chunks_ids = {
            int(r[0]) for r in conn.execute("SELECT id FROM chunks")
        }
        fts_rowids = {
            int(r[0]) for r in conn.execute("SELECT rowid FROM chunks_fts")
        }
        assert fts_rowids == chunks_ids
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Changed file (size only — mtime reset, body differs in length)
# ---------------------------------------------------------------------------


def test_sync_detects_size_only_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    plugin = _make_plugin({"a.py": ("alpha", "alpha")})
    config = _initial_build(tmp_path, monkeypatch, plugin)

    target = tmp_path / "a.py"
    original_mtime = os.stat(target).st_mtime

    # Replace contents (different length) and reset mtime to the original.
    new_text = "alpha_longer_body"
    target.write_text(new_text, encoding="utf-8")
    os.utime(target, (original_mtime, original_mtime))

    plugin.chunks_by_path["a.py"] = [
        Chunk(
            start_line=1,
            end_line=1,
            kind="function",
            name="alpha2",
            scope=None,
            text=new_text,
        )
    ]
    plugin.symbols_by_path["a.py"] = [
        Symbol(name="alpha2", kind="def", line=1)
    ]

    result = sync_module.sync(config, tmp_path)
    assert result.files_changed == 1
    assert result.files_unchanged == 0
    assert result.chunks_inserted_total == 1


# ---------------------------------------------------------------------------
# 5. Removed file
# ---------------------------------------------------------------------------


def test_sync_detects_removed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta", encoding="utf-8")
    plugin = _make_plugin(
        {"a.py": ("alpha", "alpha"), "b.py": ("beta", "beta")}
    )
    config = _initial_build(tmp_path, monkeypatch, plugin)

    (tmp_path / "b.py").unlink()

    result = sync_module.sync(config, tmp_path)
    assert result.files_removed == 1
    assert result.files_unchanged == 1
    assert result.files_added == 0
    assert result.files_changed == 0

    conn = _db_conn(tmp_path)
    try:
        for table, where in (
            ("chunks", "path = 'b.py'"),
            ("files", "path = 'b.py'"),
        ):
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}"
            ).fetchone()
            assert row is not None and row[0] == 0, (table, row)
        # No symbols / edges / embeddings / chunks_fts left over either —
        # the only rows for that file would have hung off a chunks.id that
        # no longer exists, so this also probes the cascading delete.
        for table in ("symbols", "embeddings", "chunks_fts", "edges"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            # a.py still has its rows.
            assert row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Mixed: 1 added, 1 changed, 1 removed, 2 unchanged
# ---------------------------------------------------------------------------


def test_sync_mixed_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("u1.py", "u2.py", "ch.py", "rm.py"):
        (tmp_path / name).write_text(name.split(".")[0], encoding="utf-8")
    plugin = _make_plugin(
        {
            "u1.py": ("u1", "u1"),
            "u2.py": ("u2", "u2"),
            "ch.py": ("ch", "ch"),
            "rm.py": ("rm", "rm"),
        }
    )
    config = _initial_build(tmp_path, monkeypatch, plugin)

    # 1 removed.
    (tmp_path / "rm.py").unlink()
    # 1 changed — rewrite body and bump mtime by 2 seconds.
    changed = tmp_path / "ch.py"
    changed.write_text("ch_v2_longer", encoding="utf-8")
    new_mtime = os.stat(changed).st_mtime + 2.0
    os.utime(changed, (new_mtime, new_mtime))
    plugin.chunks_by_path["ch.py"] = [
        Chunk(
            start_line=1,
            end_line=1,
            kind="function",
            name="ch2",
            scope=None,
            text="ch_v2_longer",
        )
    ]
    plugin.symbols_by_path["ch.py"] = [
        Symbol(name="ch2", kind="def", line=1)
    ]
    # 1 added.
    added = tmp_path / "new.py"
    added.write_text("new", encoding="utf-8")
    plugin.chunks_by_path["new.py"] = [
        Chunk(
            start_line=1,
            end_line=1,
            kind="function",
            name="new",
            scope=None,
            text="new",
        )
    ]
    plugin.symbols_by_path["new.py"] = [
        Symbol(name="new", kind="def", line=1)
    ]

    result = sync_module.sync(config, tmp_path)
    assert result.files_added == 1
    assert result.files_changed == 1
    assert result.files_removed == 1
    assert result.files_unchanged == 2
    assert result.chunks_inserted_total == 2


# ---------------------------------------------------------------------------
# 7. delete_file_rows happy path (direct unit test)
# ---------------------------------------------------------------------------


def test_delete_file_rows_targets_only_path(tmp_path: Path) -> None:
    """Sentinel rows for path 'x' go; rows for path 'y' stay."""
    conn = open_index(tmp_path / "scratch.sqlite")
    try:
        # Insert chunks rows for both paths.
        for path in ("x", "y"):
            cursor = conn.execute(
                "INSERT INTO chunks("
                "  path, language, project, start_line, end_line, "
                "  kind, name, scope, content"
                ") VALUES (?, 'python', 'p', 1, 1, 'f', ?, NULL, 'body')",
                (path, path),
            )
            chunk_id = cursor.lastrowid
            assert chunk_id is not None
            conn.execute(
                "INSERT INTO chunks_fts(rowid, content, name, scope) "
                "VALUES (?, 'body', ?, NULL)",
                (chunk_id, path),
            )
            conn.execute(
                "INSERT INTO embeddings(chunk_id, embedding) VALUES (?, ?)",
                (
                    chunk_id,
                    np.zeros(_EMBED_DIM, dtype=np.float32).tobytes(),
                ),
            )
            conn.execute(
                "INSERT INTO symbols(chunk_id, name, kind, line) "
                "VALUES (?, ?, 'def', 1)",
                (chunk_id, path),
            )
            conn.execute(
                "INSERT INTO edges(src_chunk_id, dst_name, kind, meta) "
                "VALUES (?, ?, 'import', NULL)",
                (chunk_id, f"{path}_dep"),
            )
            conn.execute(
                "INSERT INTO files(path, mtime, size) VALUES (?, 0.0, 0)",
                (path,),
            )

        sync_module.delete_file_rows(conn, "x")

        # Every row for 'x' is gone.
        for table, where in (
            ("chunks", "path = 'x'"),
            ("files", "path = 'x'"),
            ("symbols", "name = 'x'"),
            ("edges", "dst_name = 'x_dep'"),
        ):
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}"
            ).fetchone()
            assert row is not None and row[0] == 0, (table, row)
        # embeddings + chunks_fts cleared by chunk-id join.
        chunks_for_x = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE path = 'x'"
        ).fetchone()
        assert chunks_for_x is not None and chunks_for_x[0] == 0

        # Every row for 'y' survives.
        for table, where in (
            ("chunks", "path = 'y'"),
            ("files", "path = 'y'"),
            ("symbols", "name = 'y'"),
            ("edges", "dst_name = 'y_dep'"),
        ):
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}"
            ).fetchone()
            assert row is not None and row[0] == 1, (table, row)
        # And the embedding for y is still there (joined via the surviving
        # chunks.id for path 'y').
        emb_row = conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE chunk_id IN "
            "(SELECT id FROM chunks WHERE path = 'y')"
        ).fetchone()
        assert emb_row is not None and emb_row[0] == 1
        fts_row = conn.execute(
            "SELECT COUNT(*) FROM chunks_fts WHERE rowid IN "
            "(SELECT id FROM chunks WHERE path = 'y')"
        ).fetchone()
        assert fts_row is not None and fts_row[0] == 1
    finally:
        conn.close()
