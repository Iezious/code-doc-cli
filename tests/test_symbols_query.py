"""Tests for :func:`code_index.symbols.query_symbols`.

Pure SQL exercise — populates ``chunks`` + ``symbols`` directly via the
schema set up by :func:`code_index.storage.open_index`, then runs the query
layer. No plugins, no embedding backend.

Cases pinned in ``docs/plans/006.sync-symbols-graph/003.symbols.md`` "Tests":

1. Substring match.
2. Exact match.
3. Case sensitivity (exact and substring).
4. Language filter.
5. ``kind=def`` vs ``kind=ref``.
6. Scope is surfaced (string and ``None``).
7. Empty result.
8. Sort order by ``(path, line)``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from code_index.storage import open_index
from code_index.symbols import SymbolHit, query_symbols

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


def _insert_symbol(
    conn: sqlite3.Connection,
    chunk_id: int,
    *,
    name: str,
    kind: str = "def",
    line: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO symbols(chunk_id, name, kind, line) VALUES (?, ?, ?, ?)",
        (chunk_id, name, kind, line),
    )


def _open(tmp_path: Path) -> sqlite3.Connection:
    return open_index(tmp_path / "scratch.sqlite")


# ---------------------------------------------------------------------------
# 1. Substring match
# ---------------------------------------------------------------------------


def test_substring_match_returns_all_containing(tmp_path: Path) -> None:
    """``foo`` substring returns ``foo`` / ``foobar`` / ``barfoo`` but not ``baz``."""
    conn = _open(tmp_path)
    try:
        for name in ("foo", "foobar", "barfoo", "baz"):
            cid = _insert_chunk(conn, path=f"src/{name}.py")
            _insert_symbol(conn, cid, name=name)
        conn.commit()

        hits: list[SymbolHit] = query_symbols(conn, "foo", kind="def")
        names = sorted(h.name for h in hits)
        assert names == ["barfoo", "foo", "foobar"]

        baz_hits: list[SymbolHit] = query_symbols(conn, "baz", kind="def")
        assert [h.name for h in baz_hits] == ["baz"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Exact match
# ---------------------------------------------------------------------------


def test_exact_match_only_returns_exact_name(tmp_path: Path) -> None:
    """``--exact foo`` returns only ``foo``, not ``foobar`` / ``barfoo``."""
    conn = _open(tmp_path)
    try:
        for name in ("foo", "foobar", "barfoo", "baz"):
            cid = _insert_chunk(conn, path=f"src/{name}.py")
            _insert_symbol(conn, cid, name=name)
        conn.commit()

        hits: list[SymbolHit] = query_symbols(
            conn, "foo", kind="def", exact=True
        )
        assert [h.name for h in hits] == ["foo"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Case sensitivity (exact and substring)
# ---------------------------------------------------------------------------


def test_case_sensitive_matching(tmp_path: Path) -> None:
    """``foo`` and ``Foo`` are distinct under both exact and substring modes."""
    conn = _open(tmp_path)
    try:
        cid_lower = _insert_chunk(conn, path="src/lower.py")
        _insert_symbol(conn, cid_lower, name="foo")
        cid_upper = _insert_chunk(conn, path="src/upper.py")
        _insert_symbol(conn, cid_upper, name="Foo")
        conn.commit()

        # Exact mode is case-sensitive.
        exact_lower: list[SymbolHit] = query_symbols(
            conn, "foo", kind="def", exact=True
        )
        assert [h.name for h in exact_lower] == ["foo"]
        exact_upper: list[SymbolHit] = query_symbols(
            conn, "Foo", kind="def", exact=True
        )
        assert [h.name for h in exact_upper] == ["Foo"]

        # Substring mode is also case-sensitive — ``oo`` matches both.
        sub_lower: list[SymbolHit] = query_symbols(conn, "oo", kind="def")
        assert sorted(h.name for h in sub_lower) == ["Foo", "foo"]
        # ``OO`` matches neither.
        sub_upper: list[SymbolHit] = query_symbols(conn, "OO", kind="def")
        assert sub_upper == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Language filter
# ---------------------------------------------------------------------------


def test_language_filter_narrows_to_one_language(tmp_path: Path) -> None:
    """``--lang python`` excludes the csharp row with the same symbol name."""
    conn = _open(tmp_path)
    try:
        cid_py = _insert_chunk(conn, path="src/x.py", language="python")
        _insert_symbol(conn, cid_py, name="X")
        cid_cs = _insert_chunk(conn, path="src/X.cs", language="csharp")
        _insert_symbol(conn, cid_cs, name="X")
        conn.commit()

        py_hits: list[SymbolHit] = query_symbols(
            conn, "X", kind="def", language="python"
        )
        assert [h.language for h in py_hits] == ["python"]
        assert [h.path for h in py_hits] == ["src/x.py"]

        # Without the filter, both rows come back.
        all_hits: list[SymbolHit] = query_symbols(conn, "X", kind="def")
        assert sorted(h.language for h in all_hits) == ["csharp", "python"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. kind=def vs kind=ref
# ---------------------------------------------------------------------------


def test_kind_def_vs_ref_are_disjoint(tmp_path: Path) -> None:
    """A ``def`` row and a ``ref`` row with the same name don't bleed across."""
    conn = _open(tmp_path)
    try:
        cid_def = _insert_chunk(conn, path="src/def.py")
        _insert_symbol(conn, cid_def, name="alpha", kind="def")
        cid_ref = _insert_chunk(conn, path="src/ref.py")
        _insert_symbol(conn, cid_ref, name="alpha", kind="ref")
        conn.commit()

        def_hits: list[SymbolHit] = query_symbols(conn, "alpha", kind="def")
        assert [h.path for h in def_hits] == ["src/def.py"]

        ref_hits: list[SymbolHit] = query_symbols(conn, "alpha", kind="ref")
        assert [h.path for h in ref_hits] == ["src/ref.py"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Scope is surfaced (string and None)
# ---------------------------------------------------------------------------


def test_scope_is_surfaced_from_chunks(tmp_path: Path) -> None:
    """``chunks.scope`` flows through to :class:`SymbolHit.scope` (incl. ``None``)."""
    conn = _open(tmp_path)
    try:
        cid_scoped = _insert_chunk(
            conn, path="src/scoped.py", scope="MyModule.MyClass"
        )
        _insert_symbol(conn, cid_scoped, name="scoped_method")
        cid_unscoped = _insert_chunk(conn, path="src/unscoped.py", scope=None)
        _insert_symbol(conn, cid_unscoped, name="bare_func")
        conn.commit()

        scoped_hits: list[SymbolHit] = query_symbols(
            conn, "scoped_method", kind="def", exact=True
        )
        assert len(scoped_hits) == 1
        assert scoped_hits[0].scope == "MyModule.MyClass"

        bare_hits: list[SymbolHit] = query_symbols(
            conn, "bare_func", kind="def", exact=True
        )
        assert len(bare_hits) == 1
        assert bare_hits[0].scope is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Empty result
# ---------------------------------------------------------------------------


def test_empty_db_returns_empty_list(tmp_path: Path) -> None:
    """Query against an empty index returns ``[]``, not an error."""
    conn = _open(tmp_path)
    try:
        hits: list[SymbolHit] = query_symbols(conn, "anything", kind="def")
        assert hits == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. Sort order
# ---------------------------------------------------------------------------


def test_sort_order_by_path_then_line(tmp_path: Path) -> None:
    """Two hits in one path return sorted by ``(path, line)``."""
    conn = _open(tmp_path)
    try:
        # Two chunks in same file at different lines.
        cid_a_first = _insert_chunk(
            conn, path="src/a.py", start_line=10, end_line=10
        )
        _insert_symbol(conn, cid_a_first, name="thing", line=10)
        cid_a_second = _insert_chunk(
            conn, path="src/a.py", start_line=20, end_line=20
        )
        _insert_symbol(conn, cid_a_second, name="thing", line=20)
        # And one in a different (alphabetically later) path.
        cid_b = _insert_chunk(conn, path="src/b.py", start_line=5, end_line=5)
        _insert_symbol(conn, cid_b, name="thing", line=5)
        conn.commit()

        hits: list[SymbolHit] = query_symbols(conn, "thing", kind="def")
        assert [(h.path, h.line) for h in hits] == [
            ("src/a.py", 10),
            ("src/a.py", 20),
            ("src/b.py", 5),
        ]
    finally:
        conn.close()
