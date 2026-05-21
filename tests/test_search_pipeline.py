"""Unit tests for :mod:`code_index.search`.

Uses a synthetic 4-dim SQLite index (per ``001.context.md`` — open via
``open_index`` then drop+recreate ``embeddings`` at ``FLOAT[4]``) plus an
in-memory ``FakeBackend``. No real fastembed download is required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from code_index.search import (
    EXCERPT_MAX_LINES,
    RRF_K,
    SearchFilters,
    SearchResult,
    _rrf_fuse,
    search,
)
from code_index.storage import open_index, set_meta

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeBackend:
    """Tiny in-memory embedding backend for tests.

    ``encode`` returns the per-text vector from ``mapping``, falling back
    to the zero vector when a text is not in the mapping. ``name`` and
    ``dim`` match the synthetic index meta rows.
    """

    name: str = "fake:tiny"
    dim: int = 4

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for index, text in enumerate(texts):
            vec = self._mapping.get(text)
            if vec is not None:
                out[index] = np.asarray(vec, dtype=np.float32)
        return out


def _make_index(tmp_path: Path) -> sqlite3.Connection:
    """Open a fresh index and rebuild ``embeddings`` at ``FLOAT[4]``.

    The Phase 1 migration pins ``FLOAT[768]``; tests need short vectors,
    so we drop and recreate the vec0 virtual table with the smaller dim.
    The FTS5 trigger uses ``content='chunks'``, which means we have to
    rebuild the FTS index after inserting ``chunks`` rows.
    """
    db_path = tmp_path / "index.sqlite"
    conn = open_index(db_path)
    conn.execute("DROP TABLE embeddings")
    conn.execute(
        "CREATE VIRTUAL TABLE embeddings USING vec0("
        "  chunk_id INTEGER PRIMARY KEY, embedding FLOAT[4]"
        ")"
    )
    set_meta(conn, "embed_model", "fake:tiny")
    set_meta(conn, "embed_dim", "4")
    conn.commit()
    return conn


def _insert_chunk(
    conn: sqlite3.Connection,
    *,
    chunk_id: int,
    path: str,
    language: str,
    kind: str,
    name: str | None,
    scope: str | None,
    content: str,
    vector: list[float],
    start_line: int = 1,
    end_line: int = 1,
) -> None:
    """Insert one ``chunks`` row, its embedding, and let FTS5 catch up later."""
    conn.execute(
        "INSERT INTO chunks("
        "  id, path, language, project, start_line, end_line, "
        "  kind, name, scope, content"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            chunk_id,
            path,
            language,
            "test_project",
            start_line,
            end_line,
            kind,
            name,
            scope,
            content,
        ),
    )
    conn.execute(
        "INSERT INTO embeddings(chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, np.asarray(vector, dtype=np.float32).tobytes()),
    )


def _rebuild_fts(conn: sqlite3.Connection) -> None:
    """Run the contentless FTS5 rebuild command after bulk chunk inserts."""
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    conn.commit()


# ---------------------------------------------------------------------------
# Constant guard
# ---------------------------------------------------------------------------


def test_rrf_k_constant() -> None:
    assert RRF_K == 60


def test_excerpt_max_lines_constant() -> None:
    assert EXCERPT_MAX_LINES == 30


# ---------------------------------------------------------------------------
# Single-pool behavior
# ---------------------------------------------------------------------------


def test_bm25_only_returns_token_match(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="llListenRemove",
            scope=None,
            content="def llListenRemove():\n    pass",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        _insert_chunk(
            conn,
            chunk_id=2,
            path="src/b.py",
            language="python",
            kind="function",
            name="other_helper",
            scope=None,
            content="def other_helper():\n    return 1",
            vector=[0.0, 1.0, 0.0, 0.0],
        )
        _rebuild_fts(conn)

        results = search(conn, "llListenRemove", backend=None, mode="bm25")

        assert results, "expected at least one BM25 hit"
        assert results[0].name == "llListenRemove"
        assert results[0].path == "src/a.py"
    finally:
        conn.close()


def test_dense_only_returns_nearest_vector(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="alpha",
            scope=None,
            content="alpha body",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        _insert_chunk(
            conn,
            chunk_id=2,
            path="src/b.py",
            language="python",
            kind="function",
            name="beta",
            scope=None,
            content="beta body",
            vector=[0.0, 1.0, 0.0, 0.0],
        )
        _rebuild_fts(conn)

        backend = FakeBackend({"find alpha": [1.0, 0.0, 0.0, 0.0]})
        results = search(conn, "find alpha", backend=backend, mode="dense")

        assert results
        assert results[0].name == "alpha"
    finally:
        conn.close()


def test_bm25_mode_accepts_none_backend(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="hello",
            scope=None,
            content="hello world",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        _rebuild_fts(conn)

        # Should not raise.
        results = search(conn, "hello", backend=None, mode="bm25")
        assert results
    finally:
        conn.close()


def test_dense_mode_requires_backend(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        with pytest.raises(ValueError):
            search(conn, "anything", backend=None, mode="dense")
        with pytest.raises(ValueError):
            search(conn, "anything", backend=None, mode="hybrid")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hybrid fusion
# ---------------------------------------------------------------------------


def test_hybrid_fuses_both_pools(tmp_path: Path) -> None:
    """Lexical winner and dense winner are distinct chunks; hybrid keeps both."""
    conn = _make_index(tmp_path)
    try:
        # Chunk 1: lexical winner (contains "uniquetoken"), poor dense match.
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="lex_winner",
            scope=None,
            content="def lex_winner():\n    uniquetoken = 1",
            vector=[0.0, 0.0, 1.0, 0.0],
        )
        # Chunk 2: dense winner (vector matches query), no lexical match.
        _insert_chunk(
            conn,
            chunk_id=2,
            path="src/b.py",
            language="python",
            kind="function",
            name="dense_winner",
            scope=None,
            content="def dense_winner():\n    return 0",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        # Chunk 3: noise.
        _insert_chunk(
            conn,
            chunk_id=3,
            path="src/c.py",
            language="python",
            kind="function",
            name="noise",
            scope=None,
            content="def noise():\n    pass",
            vector=[0.0, 1.0, 0.0, 0.0],
        )
        _rebuild_fts(conn)

        backend = FakeBackend({"uniquetoken": [1.0, 0.0, 0.0, 0.0]})
        results = search(
            conn, "uniquetoken", backend=backend, mode="hybrid", k=10
        )

        names = [r.name for r in results]
        # Both pool winners must be present in the fused list.
        assert "lex_winner" in names
        assert "dense_winner" in names
        # The top-ranked result must have the highest fused score (the
        # invariant we care about); ties are documented in
        # test_rrf_tie_break_prefers_dense_rank.
        assert results[0].score == max(r.score for r in results)
        # noise must not outrank either winner.
        noise_index = names.index("noise") if "noise" in names else len(names)
        assert names.index("lex_winner") < noise_index
        assert names.index("dense_winner") < noise_index
    finally:
        conn.close()


def test_rrf_tie_break_prefers_dense_rank() -> None:
    """Items with identical fused score: lower dense rank wins; absent last."""
    # Both items at rank 1 of their pool -> same per-pool contribution.
    # Item A appears in both pools (so it's not present-vs-absent).
    # Compare: item B is in BM25 only (absent from dense).
    fused = _rrf_fuse(
        bm25=[(10, 1), (20, 1)],
        dense=[(10, 5)],
    )
    # Both: A=10 has bm25 rank 1 + dense rank 5; B=20 has bm25 rank 1 only.
    # Scores differ; the test below covers the present-vs-absent rule.
    chunk_ids = [cid for cid, _ in fused]
    assert chunk_ids[0] == 10  # higher fused score

    # Now construct an actual tie: two items with identical contributions
    # but different dense ranks. A is at bm25 rank 5, dense rank 2.
    # B is at bm25 rank 5, dense rank 1. Identical bm25 contribution;
    # B's lower dense rank gives it a higher fused score (not a true tie),
    # so the tie-break key still places B first.
    fused = _rrf_fuse(
        bm25=[(99, 5), (88, 5)],
        dense=[(88, 1), (99, 2)],
    )
    assert fused[0][0] == 88

    # True tie on score: two items contribute the same total. Item A has
    # bm25 rank 1 only; item B has dense rank 1 only. Same numerical
    # score (1 / (60 + 1)). Tie-break: the one with a dense rank wins;
    # absent-from-dense sorts after.
    fused = _rrf_fuse(
        bm25=[(7, 1)],
        dense=[(8, 1)],
    )
    score_7 = next(s for cid, s in fused if cid == 7)
    score_8 = next(s for cid, s in fused if cid == 8)
    assert score_7 == pytest.approx(score_8)
    # Lower dense rank wins; item 7 is absent from dense, so 8 sorts first.
    assert fused[0][0] == 8


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _populate_filter_corpus(conn: sqlite3.Connection) -> None:
    _insert_chunk(
        conn,
        chunk_id=1,
        path="src/foo/a.py",
        language="python",
        kind="function",
        name="needle_py_fn",
        scope=None,
        content="def needle_py_fn():\n    needle = 1",
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    _insert_chunk(
        conn,
        chunk_id=2,
        path="src/foo/a.go",
        language="go",
        kind="function",
        name="needle_go_fn",
        scope=None,
        content="func needle_go_fn() {\n    needle := 1\n}",
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    _insert_chunk(
        conn,
        chunk_id=3,
        path="src/bar/c.py",
        language="python",
        kind="class",
        name="NeedleClass",
        scope=None,
        content="class NeedleClass:\n    needle = 1",
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    _rebuild_fts(conn)


def test_filter_lang_applied_to_both_pools(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _populate_filter_corpus(conn)
        backend = FakeBackend({"needle": [1.0, 0.0, 0.0, 0.0]})
        results = search(
            conn,
            "needle",
            backend=backend,
            mode="hybrid",
            filters=SearchFilters(lang="python"),
        )
        assert results
        assert all(r.language == "python" for r in results)
    finally:
        conn.close()


def test_filter_kind_applied(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _populate_filter_corpus(conn)
        backend = FakeBackend({"needle": [1.0, 0.0, 0.0, 0.0]})
        results = search(
            conn,
            "needle",
            backend=backend,
            mode="hybrid",
            filters=SearchFilters(kind="class"),
        )
        assert results
        assert all(r.kind == "class" for r in results)
    finally:
        conn.close()


def test_filter_path_glob_applied(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _populate_filter_corpus(conn)
        backend = FakeBackend({"needle": [1.0, 0.0, 0.0, 0.0]})
        results = search(
            conn,
            "needle",
            backend=backend,
            mode="hybrid",
            filters=SearchFilters(path_glob="src/foo/*"),
        )
        assert results
        assert all(r.path.startswith("src/foo/") for r in results)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_zero_results_returns_empty_list(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="something",
            scope=None,
            content="something",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        _rebuild_fts(conn)

        results = search(
            conn, "xxxnotpresentxxx", backend=None, mode="bm25"
        )
        assert results == []
    finally:
        conn.close()


def test_excerpt_truncated_to_30_lines(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        long_content = "\n".join(f"line{i}" for i in range(100))
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="biggie",
            scope=None,
            content=long_content,
            vector=[1.0, 0.0, 0.0, 0.0],
            start_line=1,
            end_line=100,
        )
        _rebuild_fts(conn)

        results = search(conn, "biggie", backend=None, mode="bm25")
        assert results
        excerpt = results[0].excerpt
        assert excerpt.count("\n") + 1 <= EXCERPT_MAX_LINES
        # First lines must be present; line29 (0-indexed) is the 30th line.
        assert excerpt.startswith("line0\n")
        assert "line29" in excerpt
        assert "line30" not in excerpt
        # No trailing newline appended.
        assert not excerpt.endswith("\n")
    finally:
        conn.close()


def test_k_limits_returned_rows(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        # 50 BM25-matching chunks.
        for i in range(50):
            _insert_chunk(
                conn,
                chunk_id=i + 1,
                path=f"src/f_{i}.py",
                language="python",
                kind="function",
                name=f"matchme_{i}",
                scope=None,
                content=f"matchme {i}",
                vector=[1.0, 0.0, 0.0, 0.0],
            )
        _rebuild_fts(conn)

        results = search(conn, "matchme", backend=None, mode="bm25", k=5)
        assert len(results) == 5
    finally:
        conn.close()


def test_bm25_k_caps_candidate_pool(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        for i in range(200):
            _insert_chunk(
                conn,
                chunk_id=i + 1,
                path=f"src/f_{i}.py",
                language="python",
                kind="function",
                name=f"matchme_{i}",
                scope=None,
                content=f"matchme {i}",
                vector=[1.0, 0.0, 0.0, 0.0],
            )
        _rebuild_fts(conn)

        results = search(
            conn, "matchme", backend=None, mode="bm25", k=20, bm25_k=10
        )
        # The candidate pool is capped at 10, so at most 10 results survive
        # to hydration even though k=20.
        assert len(results) <= 10
    finally:
        conn.close()


def test_search_result_shape(tmp_path: Path) -> None:
    conn = _make_index(tmp_path)
    try:
        _insert_chunk(
            conn,
            chunk_id=1,
            path="src/a.py",
            language="python",
            kind="function",
            name="shape_test",
            scope="module",
            content="def shape_test():\n    pass",
            vector=[1.0, 0.0, 0.0, 0.0],
            start_line=10,
            end_line=12,
        )
        _rebuild_fts(conn)

        results = search(conn, "shape_test", backend=None, mode="bm25")
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, SearchResult)
        assert result.path == "src/a.py"
        assert result.start_line == 10
        assert result.end_line == 12
        assert result.language == "python"
        assert result.kind == "function"
        assert result.name == "shape_test"
        assert result.scope == "module"
        assert "shape_test" in result.excerpt
        assert result.score > 0
    finally:
        conn.close()
