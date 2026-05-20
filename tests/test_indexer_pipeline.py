"""Tests for the indexer pipeline.

Eight cases per ``docs/plans/004.walker-and-build/003.indexer-pipeline.md``:

1. Fresh DB, happy path.
2. ``files`` table populated.
3. Pre-populated DB (auto-rebuild).
4. ``dry_run=True``.
5. Plugin raise.
6. Per-file IO error.
7. Empty input.
8. Embedding batching.

The tests build their own resolved ``CodeIndexConfig``, monkeypatch
``code_index.indexer.active_plugins`` and ``code_index.indexer.from_config``
to inject fake plugins and a fake embedding backend, and exercise
:func:`code_index.indexer.build` against a tmp-path project tree. The
SQLite DB is real and opened via the Phase 1 storage helper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

from code_index import indexer, walker
from code_index.config import CodeIndexConfig
from code_index.languages import Chunk, Edge, Symbol
from code_index.languages.registry import LanguageRegistry
from code_index.storage import get_meta, open_index

if TYPE_CHECKING:
    pass


_EMBED_DIM: int = 768


# ---------------------------------------------------------------------------
# Fake plugin / backend doubles
# ---------------------------------------------------------------------------


@dataclass
class FakePlugin:
    """Test double exposing the structural ``Language`` Protocol.

    Each method returns canned values keyed by file path: tests build a
    ``{Path: list[...]}`` map and the plugin returns the matching list
    (defaulting to empty). Setting ``raise_on`` to a path basename makes the
    three methods raise on that file; we route the raise through ``chunk``
    so the indexer's single try-block catches it.
    """

    name: str
    extensions: tuple[str, ...]
    chunks_by_path: dict[str, list[Chunk]]
    symbols_by_path: dict[str, list[Symbol]]
    edges_by_path: dict[str, list[Edge]]
    raise_on: str | None = None

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        del content
        if self.raise_on is not None and path.name == self.raise_on:
            raise RuntimeError("synthetic plugin failure")
        return list(self.chunks_by_path.get(path.name, []))

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        del content
        return list(self.symbols_by_path.get(path.name, []))

    def imports(self, path: Path, content: str) -> list[Edge]:
        del content
        return list(self.edges_by_path.get(path.name, []))


class FakeBackend:
    """Deterministic embedding backend for tests.

    Returns ``(len(texts), 768)`` float32 vectors built from a per-text
    seed so the same text round-trips to the same vector. Tracks the
    sequence of ``encode`` calls so tests can assert batching.
    """

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
            # First two coords carry a deterministic signature so tests
            # can sanity-check the vector if needed.
            out[i, 0] = float(len(text))
            out[i, 1] = float(i)
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    project_root: Path,
    languages: list[str],
    embed_batch_size: int = 32,
) -> CodeIndexConfig:
    """Build a resolved config sufficient to drive ``build``.

    The walker reads ``languages`` / ``extra_languages`` / ``ignores`` only;
    the rest of the fields just have to satisfy the pydantic shape.
    """
    del project_root  # walker.walk receives the root explicitly
    return CodeIndexConfig(
        version=">=0.1,<1.0",
        project="indexer-test",
        roots=["."],
        ignores=[],
        languages=languages,
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
    """Wire fake plugins and a fake backend into the indexer module."""
    registry = LanguageRegistry(plugins)  # type: ignore[arg-type]
    monkeypatch.setattr(
        indexer, "active_plugins", lambda config: registry
    )
    # The walker has its own import of `active_plugins` for extension
    # filtering; patch it too so the walker yields our test extensions.
    monkeypatch.setattr(
        walker, "active_plugins", lambda config: registry
    )
    monkeypatch.setattr(
        indexer, "from_config", lambda config: backend
    )


def _two_file_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project tree with one ``.py`` and one ``.foo`` source file."""
    py_path = tmp_path / "a.py"
    py_path.write_text("def a(): pass\n", encoding="utf-8")
    foo_path = tmp_path / "b.foo"
    foo_path.write_text("foo content here\n", encoding="utf-8")
    return py_path, foo_path


def _two_plugins() -> tuple[FakePlugin, FakePlugin]:
    """Build two plugins that each emit two chunks / one symbol / one edge."""
    py_plugin = FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path={
            "a.py": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="function",
                    name="a",
                    scope=None,
                    text="def a(): pass",
                ),
                Chunk(
                    start_line=2,
                    end_line=2,
                    kind="module",
                    name=None,
                    scope=None,
                    text="trailing",
                ),
            ]
        },
        symbols_by_path={
            "a.py": [Symbol(name="a", kind="def", line=1)],
        },
        edges_by_path={
            "a.py": [Edge(target="os", kind="import", line=0, meta=None)],
        },
    )
    foo_plugin = FakePlugin(
        name="foo",
        extensions=(".foo",),
        chunks_by_path={
            "b.foo": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="state",
                    name="root",
                    scope=None,
                    text="foo content here",
                ),
                Chunk(
                    start_line=2,
                    end_line=2,
                    kind="state",
                    name="extra",
                    scope=None,
                    text="more foo",
                ),
            ]
        },
        symbols_by_path={
            "b.foo": [Symbol(name="root", kind="def", line=1)],
        },
        edges_by_path={
            "b.foo": [Edge(target="bar", kind="call", line=1, meta={"k": "v"})],
        },
    )
    return py_plugin, foo_plugin


def _db_conn(tmp_path: Path):  # noqa: ANN202 — sqlite3.Connection
    """Open the index DB the indexer wrote to and return the connection."""
    return open_index(tmp_path / "docs" / ".helpers" / "index.sqlite")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fresh_db_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two-file polyglot fixture indexes end-to-end with the expected counts."""
    _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)

    config = _make_config(project_root=tmp_path, languages=["python", "foo"])
    result = indexer.build(config, tmp_path)

    assert result.files_walked == 2
    assert result.files_chunked == 2
    assert result.chunks_inserted == 4
    assert result.symbols_inserted == 2
    assert result.edges_inserted == 2

    conn = _db_conn(tmp_path)
    try:
        assert get_meta(conn, "embed_model") == "fake:tiny"
        assert get_meta(conn, "embed_dim") == str(_EMBED_DIM)

        # FTS5 round-trip: a token from one of the inserted chunks must
        # come back from a chunks_fts MATCH query.
        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'content'"
        ).fetchall()
        assert len(rows) >= 1
    finally:
        conn.close()


def test_files_table_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each chunked file gets one ``files`` row with matching path/mtime/size."""
    py_path, foo_path = _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)

    config = _make_config(project_root=tmp_path, languages=["python", "foo"])
    indexer.build(config, tmp_path)

    conn = _db_conn(tmp_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
        assert row is not None and row[0] == 2

        files_rows = list(
            conn.execute("SELECT path, mtime, size FROM files ORDER BY path")
        )
        chunk_paths = {
            r[0] for r in conn.execute("SELECT DISTINCT path FROM chunks")
        }
        for path_str, mtime_val, size_val in files_rows:
            # Forward slashes; matches chunks.path byte-for-byte.
            assert "\\" not in path_str
            assert path_str in chunk_paths

            absolute: Path = (
                py_path if path_str == "a.py" else foo_path
            )
            expected_mtime: float = os.stat(absolute).st_mtime
            expected_size: int = os.stat(absolute).st_size
            assert mtime_val == pytest.approx(expected_mtime)
            assert size_val == expected_size
    finally:
        conn.close()


def test_auto_rebuild_clears_prior_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second build with a smaller fixture overwrites the prior row data."""
    # First build: two files, four chunks, etc.
    _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)
    config = _make_config(project_root=tmp_path, languages=["python", "foo"])
    indexer.build(config, tmp_path)

    # Replace fixture with a single one-chunk file.
    (tmp_path / "a.py").unlink()
    (tmp_path / "b.foo").unlink()
    single_path = tmp_path / "c.py"
    single_path.write_text("def c(): pass\n", encoding="utf-8")

    smaller_py = FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path={
            "c.py": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="function",
                    name="c",
                    scope=None,
                    text="def c(): pass",
                )
            ]
        },
        symbols_by_path={"c.py": [Symbol(name="c", kind="def", line=1)]},
        edges_by_path={},
    )
    backend2 = FakeBackend()
    _patch_pipeline(monkeypatch, [smaller_py], backend2)
    config2 = _make_config(project_root=tmp_path, languages=["python"])
    result = indexer.build(config2, tmp_path)

    assert result.chunks_inserted == 1

    conn = _db_conn(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        # schema_version preserved.
        assert get_meta(conn, "schema_version") is not None
    finally:
        conn.close()


def test_dry_run_skips_encode_and_inserts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walker + chunker run; backend.encode and DB inserts are skipped."""
    _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)
    config = _make_config(project_root=tmp_path, languages=["python", "foo"])

    result = indexer.build(config, tmp_path, dry_run=True)

    # Walk + chunk ran; backend never called; chunks_inserted reflects that.
    assert result.files_walked == 2
    assert result.files_chunked == 2
    assert result.chunks_inserted == 0
    assert backend.calls == []

    conn = _db_conn(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    finally:
        conn.close()


def test_plugin_raise_skips_file_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A plugin raise on one file skips that file but indexes the others."""
    _two_file_fixture(tmp_path)
    py_plugin, foo_plugin = _two_plugins()
    foo_plugin.raise_on = "b.foo"
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, [py_plugin, foo_plugin], backend)
    config = _make_config(project_root=tmp_path, languages=["python", "foo"])

    result = indexer.build(config, tmp_path)

    # One file succeeded; the other was skipped.
    assert result.files_walked == 2
    assert result.files_chunked == 1
    assert result.chunks_inserted == 2

    captured = capsys.readouterr()
    assert "plugin foo raised on b.foo: synthetic plugin failure" in captured.err

    conn = _db_conn(tmp_path)
    try:
        paths = {
            row[0] for row in conn.execute("SELECT DISTINCT path FROM chunks")
        }
        assert paths == {"a.py"}
        files_paths = {row[0] for row in conn.execute("SELECT path FROM files")}
        assert files_paths == {"a.py"}
        sym_rows = list(conn.execute("SELECT name FROM symbols"))
        assert len(sym_rows) == 1
        edge_rows = list(conn.execute("SELECT dst_name FROM edges"))
        assert len(edge_rows) == 1
    finally:
        conn.close()


def test_io_error_skips_file_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stat failure on one file lands a warning and skips that file only."""
    _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)
    config = _make_config(project_root=tmp_path, languages=["python", "foo"])

    real_stat_file = indexer._stat_file

    def _stat_with_fault(path: Path) -> os.stat_result:
        # Make a stat against the .foo file blow up — only the indexer's
        # post-chunk stat call goes through ``_stat_file``, so the walker's
        # own stat usage is unaffected.
        if path.name == "b.foo":
            raise OSError("synthetic stat failure")
        return real_stat_file(path)

    monkeypatch.setattr(indexer, "_stat_file", _stat_with_fault)

    result = indexer.build(config, tmp_path)

    assert result.files_walked == 2
    assert result.files_chunked == 1
    assert result.chunks_inserted == 2

    captured = capsys.readouterr()
    assert "io error on b.foo: synthetic stat failure" in captured.err

    conn = _db_conn(tmp_path)
    try:
        files_paths = {row[0] for row in conn.execute("SELECT path FROM files")}
        assert files_paths == {"a.py"}
    finally:
        conn.close()


def test_empty_input_no_calls_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root with no matching files produces zero counts and no encode calls."""
    # Project root exists but has no source files matching any plugin's
    # extensions.
    (tmp_path / "not_a_source.bin").write_bytes(b"\x00\x01\x02")

    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)
    config = _make_config(project_root=tmp_path, languages=["python", "foo"])

    result = indexer.build(config, tmp_path)

    assert result.files_walked == 0
    assert result.files_chunked == 0
    assert result.chunks_inserted == 0
    assert backend.calls == []

    conn = _db_conn(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    finally:
        conn.close()


def test_embedding_batching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``embed_batch_size=2`` and four chunks, ``encode`` is called twice."""
    _two_file_fixture(tmp_path)
    plugins = list(_two_plugins())
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugins, backend)
    config = _make_config(
        project_root=tmp_path, languages=["python", "foo"], embed_batch_size=2
    )

    indexer.build(config, tmp_path)

    assert len(backend.calls) == 2
    assert all(len(call) == 2 for call in backend.calls)
