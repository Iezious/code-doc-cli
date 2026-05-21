"""Tests for :func:`code_index.graph.query_callers` / :func:`query_deps`.

Pure SQL exercise — populates ``chunks`` + ``edges`` directly via the
schema set up by :func:`code_index.storage.open_index`, then runs the query
layer. No plugins, no embedding backend.

Cases pinned in ``docs/plans/006.sync-symbols-graph/004.graph.md`` "Tests":

Callers:
1. Substring match.
2. Exact match.
3. Case sensitivity (exact and substring).
4. Language filter.

Deps:
5. Exact path match.
6. No globbing (``*`` is not a wildcard).
7. No substring (must match exactly).
8. Unresolved ``dst_name`` is returned.
9. ``meta`` as raw JSON string.
10. ``meta`` as ``NULL``.

11. Sort order — callers by ``(path, start_line)``; deps by
    ``(path, kind, dst_name)``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from code_index.graph import CallerHit, DepHit, query_callers, query_deps
from code_index.storage import open_index

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _insert_chunk(
    conn: sqlite3.Connection,
    *,
    path: str,
    language: str = "python",
    scope: str | None = None,
    start_line: int = 1,
    end_line: int = 1,
) -> int:
    """Insert a ``chunks`` row, return ``chunks.id`` for FK use."""
    cursor = conn.execute(
        "INSERT INTO chunks("
        "  path, language, project, start_line, end_line, "
        "  kind, name, scope, content"
        ") VALUES (?, ?, 'p', ?, ?, 'function', NULL, ?, 'body')",
        (path, language, start_line, end_line, scope),
    )
    chunk_id = cursor.lastrowid
    assert chunk_id is not None
    return int(chunk_id)


def _insert_edge(
    conn: sqlite3.Connection,
    src_chunk_id: int,
    *,
    dst_name: str,
    kind: str = "call",
    meta: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO edges(src_chunk_id, dst_name, kind, meta) "
        "VALUES (?, ?, ?, ?)",
        (src_chunk_id, dst_name, kind, meta),
    )


def _open(tmp_path: Path) -> sqlite3.Connection:
    return open_index(tmp_path / "scratch.sqlite")


# ---------------------------------------------------------------------------
# 1. Callers substring match
# ---------------------------------------------------------------------------


def test_callers_substring_match_returns_all_containing(tmp_path: Path) -> None:
    """``foo`` substring returns edges with ``foo`` / ``foobar`` dst_name."""
    conn = _open(tmp_path)
    try:
        cid_a = _insert_chunk(conn, path="a.py", start_line=1)
        _insert_edge(conn, cid_a, dst_name="foo")
        cid_b = _insert_chunk(conn, path="b.py", start_line=1)
        _insert_edge(conn, cid_b, dst_name="foobar")
        cid_c = _insert_chunk(conn, path="c.py", start_line=1)
        _insert_edge(conn, cid_c, dst_name="baz")
        conn.commit()

        hits: list[CallerHit] = query_callers(conn, "foo")
        names = sorted(h.dst_name for h in hits)
        assert names == ["foo", "foobar"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Callers exact match
# ---------------------------------------------------------------------------


def test_callers_exact_match_only_returns_exact_dst_name(tmp_path: Path) -> None:
    """``--exact foo`` returns only edges with ``dst_name == "foo"``."""
    conn = _open(tmp_path)
    try:
        cid_a = _insert_chunk(conn, path="a.py", start_line=1)
        _insert_edge(conn, cid_a, dst_name="foo")
        cid_b = _insert_chunk(conn, path="b.py", start_line=1)
        _insert_edge(conn, cid_b, dst_name="foobar")
        conn.commit()

        hits: list[CallerHit] = query_callers(conn, "foo", exact=True)
        assert [h.dst_name for h in hits] == ["foo"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Callers case sensitivity (exact and substring)
# ---------------------------------------------------------------------------


def test_callers_case_sensitive_matching(tmp_path: Path) -> None:
    """``foo`` and ``Foo`` are distinct under both exact and substring modes."""
    conn = _open(tmp_path)
    try:
        cid_lower = _insert_chunk(conn, path="lower.py", start_line=1)
        _insert_edge(conn, cid_lower, dst_name="foo")
        cid_upper = _insert_chunk(conn, path="upper.py", start_line=1)
        _insert_edge(conn, cid_upper, dst_name="Foo")
        conn.commit()

        # Exact mode is case-sensitive.
        exact_lower: list[CallerHit] = query_callers(conn, "foo", exact=True)
        assert [h.dst_name for h in exact_lower] == ["foo"]
        exact_upper: list[CallerHit] = query_callers(conn, "Foo", exact=True)
        assert [h.dst_name for h in exact_upper] == ["Foo"]

        # Substring mode is also case-sensitive — ``oo`` matches both.
        sub_lower: list[CallerHit] = query_callers(conn, "oo")
        assert sorted(h.dst_name for h in sub_lower) == ["Foo", "foo"]
        # ``OO`` matches neither.
        sub_upper: list[CallerHit] = query_callers(conn, "OO")
        assert sub_upper == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Callers language filter
# ---------------------------------------------------------------------------


def test_callers_language_filter_narrows_to_one_language(tmp_path: Path) -> None:
    """``language="python"`` excludes the csharp row with the same dst_name."""
    conn = _open(tmp_path)
    try:
        cid_py = _insert_chunk(conn, path="x.py", language="python")
        _insert_edge(conn, cid_py, dst_name="Target")
        cid_cs = _insert_chunk(conn, path="X.cs", language="csharp")
        _insert_edge(conn, cid_cs, dst_name="Target")
        conn.commit()

        py_hits: list[CallerHit] = query_callers(
            conn, "Target", language="python"
        )
        assert [h.language for h in py_hits] == ["python"]
        assert [h.path for h in py_hits] == ["x.py"]

        # Without the filter, both rows come back.
        all_hits: list[CallerHit] = query_callers(conn, "Target")
        assert sorted(h.language for h in all_hits) == ["csharp", "python"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Deps exact path match
# ---------------------------------------------------------------------------


def test_deps_exact_path_match_returns_only_that_files_edges(tmp_path: Path) -> None:
    """``query_deps("src/a.py")`` returns only edges from chunks of ``src/a.py``."""
    conn = _open(tmp_path)
    try:
        cid_a = _insert_chunk(conn, path="src/a.py")
        _insert_edge(conn, cid_a, dst_name="os", kind="import")
        _insert_edge(conn, cid_a, dst_name="sys", kind="import")
        cid_b = _insert_chunk(conn, path="src/b.py")
        _insert_edge(conn, cid_b, dst_name="json", kind="import")
        _insert_edge(conn, cid_b, dst_name="re", kind="import")
        conn.commit()

        a_hits: list[DepHit] = query_deps(conn, "src/a.py")
        assert sorted(h.dst_name for h in a_hits) == ["os", "sys"]
        assert all(h.path == "src/a.py" for h in a_hits)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Deps no globbing
# ---------------------------------------------------------------------------


def test_deps_no_globbing(tmp_path: Path) -> None:
    """``src/a*`` is interpreted literally; returns ``[]`` since no path equals it."""
    conn = _open(tmp_path)
    try:
        cid_a = _insert_chunk(conn, path="src/a.py")
        _insert_edge(conn, cid_a, dst_name="os")
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "src/a*")
        assert hits == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Deps no substring
# ---------------------------------------------------------------------------


def test_deps_no_substring(tmp_path: Path) -> None:
    """``a.py`` does not match ``src/a.py`` — equality is strict."""
    conn = _open(tmp_path)
    try:
        cid_a = _insert_chunk(conn, path="src/a.py")
        _insert_edge(conn, cid_a, dst_name="os")
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "a.py")
        assert hits == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. Deps with unresolved dst_name
# ---------------------------------------------------------------------------


def test_deps_returns_unresolved_dst_name(tmp_path: Path) -> None:
    """An edge whose ``dst_name`` is not a known ``symbols.name`` still comes back."""
    conn = _open(tmp_path)
    try:
        cid = _insert_chunk(conn, path="src/foo.py")
        _insert_edge(conn, cid, dst_name="not_a_real_symbol", kind="call")
        # No matching symbols row inserted — the edge is unresolved.
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "src/foo.py")
        assert len(hits) == 1
        assert hits[0].dst_name == "not_a_real_symbol"
        assert hits[0].kind == "call"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 9. Deps with meta as JSON string
# ---------------------------------------------------------------------------


def test_deps_meta_is_raw_json_string(tmp_path: Path) -> None:
    """``edges.meta`` flows through to :class:`DepHit.meta` unparsed."""
    conn = _open(tmp_path)
    try:
        cid = _insert_chunk(conn, path="src/foo.py")
        _insert_edge(
            conn,
            cid,
            dst_name="channel_42",
            kind="listen",
            meta='{"channel": 42}',
        )
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "src/foo.py")
        assert len(hits) == 1
        assert hits[0].meta == '{"channel": 42}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 10. Deps with meta as NULL
# ---------------------------------------------------------------------------


def test_deps_meta_null_surfaces_as_none(tmp_path: Path) -> None:
    """``edges.meta IS NULL`` surfaces as :data:`None` (not the string ``"None"``)."""
    conn = _open(tmp_path)
    try:
        cid = _insert_chunk(conn, path="src/foo.py")
        _insert_edge(conn, cid, dst_name="os", kind="import", meta=None)
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "src/foo.py")
        assert len(hits) == 1
        assert hits[0].meta is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 11. Sort order
# ---------------------------------------------------------------------------


def test_callers_sort_order_by_path_then_start_line(tmp_path: Path) -> None:
    """Callers come back sorted by ``(chunks.path, chunks.start_line)``."""
    conn = _open(tmp_path)
    try:
        cid_a_first = _insert_chunk(conn, path="a.py", start_line=10, end_line=10)
        _insert_edge(conn, cid_a_first, dst_name="target")
        cid_a_second = _insert_chunk(
            conn, path="a.py", start_line=20, end_line=20
        )
        _insert_edge(conn, cid_a_second, dst_name="target")
        cid_b = _insert_chunk(conn, path="b.py", start_line=5, end_line=5)
        _insert_edge(conn, cid_b, dst_name="target")
        conn.commit()

        hits: list[CallerHit] = query_callers(conn, "target", exact=True)
        assert [(h.path, h.start_line) for h in hits] == [
            ("a.py", 10),
            ("a.py", 20),
            ("b.py", 5),
        ]
    finally:
        conn.close()


def test_deps_sort_order_by_path_kind_dst_name(tmp_path: Path) -> None:
    """Deps come back sorted by ``(path, kind, dst_name)``."""
    conn = _open(tmp_path)
    try:
        cid = _insert_chunk(conn, path="src/foo.py")
        # Insert in scrambled order; expect them back sorted.
        _insert_edge(conn, cid, dst_name="zeta", kind="call")
        _insert_edge(conn, cid, dst_name="alpha", kind="import")
        _insert_edge(conn, cid, dst_name="alpha", kind="call")
        _insert_edge(conn, cid, dst_name="beta", kind="import")
        conn.commit()

        hits: list[DepHit] = query_deps(conn, "src/foo.py")
        assert [(h.kind, h.dst_name) for h in hits] == [
            ("call", "alpha"),
            ("call", "zeta"),
            ("import", "alpha"),
            ("import", "beta"),
        ]
    finally:
        conn.close()
