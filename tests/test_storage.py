"""Tests for code_index.storage — open helper, migrations harness, schema v1."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import code_index
from code_index.errors import CodeIndexError
from code_index.storage import (
    CURRENT_SCHEMA_VERSION,
    get_meta,
    open_index,
    set_meta,
)
from code_index.storage.migrations import discover_migrations, run_migrations

EXPECTED_TABLES: tuple[str, ...] = (
    "meta",
    "files",
    "chunks",
    "chunks_fts",
    "embeddings",
    "symbols",
    "edges",
)

EXPECTED_INDICES: tuple[str, ...] = (
    "idx_chunks_path",
    "idx_chunks_language",
    "idx_symbols_name",
    "idx_edges_dst_name",
    "idx_edges_src_chunk_id",
)


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "index.sqlite"


def test_open_creates_fresh_db(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    assert not path.exists()

    conn = open_index(path)
    try:
        assert path.exists()
        assert get_meta(conn, "schema_version") == CURRENT_SCHEMA_VERSION
        assert get_meta(conn, "code_index_version") == code_index.__version__
    finally:
        conn.close()


def test_wal_mode_enabled(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        assert str(row[0]).lower() == "wal"
    finally:
        conn.close()


def test_fts_table_exists(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = 'chunks_fts'"
        ).fetchone()
        assert row is not None
        assert row[0] == "table"
    finally:
        conn.close()


def test_vec_table_exists(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'embeddings'"
        ).fetchone()
        assert row is not None
        assert row[0] == "embeddings"
    finally:
        conn.close()


def test_files_table_exists(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = 'files'"
        ).fetchone()
        assert row is not None
        assert row[0] == "table"

        info = list(conn.execute("PRAGMA table_info('files')"))
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk.
        by_name = {row[1]: row for row in info}
        assert set(by_name.keys()) == {"path", "mtime", "size"}

        path_row = by_name["path"]
        assert str(path_row[2]).upper() == "TEXT"
        assert path_row[5] == 1  # path is the primary key

        assert str(by_name["mtime"][2]).upper() == "REAL"
        assert str(by_name["size"][2]).upper() == "INTEGER"

        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()
        assert count is not None
        assert count[0] == 0
    finally:
        conn.close()


def test_all_indices_created(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
        names = {row[0] for row in rows}
        for expected in EXPECTED_INDICES:
            assert expected in names, f"missing index {expected!r}; got {sorted(names)}"
    finally:
        conn.close()


def test_reopen_does_not_remigrate(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = open_index(path)
    try:
        # Sentinel row in a real (non-virtual) table; if migrations ran again
        # we'd expect a CREATE TABLE to wipe the row (it does not, but this
        # round-trip still proves no DROP/recreate happened either).
        conn.execute(
            "INSERT INTO files(path, mtime, size) VALUES (?, ?, ?)",
            ("sentinel.py", 1.0, 1),
        )
        conn.commit()
    finally:
        conn.close()

    conn = open_index(path)
    try:
        assert get_meta(conn, "schema_version") == CURRENT_SCHEMA_VERSION
        row = conn.execute(
            "SELECT path, mtime, size FROM files WHERE path = 'sentinel.py'"
        ).fetchone()
        assert row == ("sentinel.py", 1.0, 1)
    finally:
        conn.close()


def test_schema_mismatch_raises(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = open_index(path)
    try:
        set_meta(conn, "schema_version", "999")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(CodeIndexError) as excinfo:
        open_index(path, check_version=True)
    assert excinfo.value.code == 10
    assert excinfo.value.kind == "index.schema_mismatch"


def test_discover_migrations_sorted() -> None:
    migrations = discover_migrations()
    assert len(migrations) >= 1
    # All from_version strings parse as ints; the list is sorted by that int.
    from_ints = [int(m.from_version) for m in migrations]
    assert from_ints == sorted(from_ints)

    # The 0 -> 1 migration is always present.
    by_from = {m.from_version: m for m in migrations}
    assert "0" in by_from
    assert by_from["0"].to_version == "1"


def test_migration_runner_idempotent(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = open_index(path)
    try:
        conn.execute(
            "INSERT INTO files(path, mtime, size) VALUES (?, ?, ?)",
            ("keep.py", 2.0, 2),
        )
        conn.commit()

        # Already at target; second call is a no-op.
        run_migrations(conn, CURRENT_SCHEMA_VERSION)

        assert get_meta(conn, "schema_version") == CURRENT_SCHEMA_VERSION
        row = conn.execute(
            "SELECT path, mtime, size FROM files WHERE path = 'keep.py'"
        ).fetchone()
        assert row == ("keep.py", 2.0, 2)
    finally:
        conn.close()


def test_vec_extension_unavailable_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import code_index.storage as storage_mod

    def _boom(conn: sqlite3.Connection) -> None:
        raise CodeIndexError(
            10,
            "index.vec_extension_unavailable",
            "patched failure",
            {"cause": "patched"},
        )

    monkeypatch.setattr(storage_mod, "_load_sqlite_vec", _boom)

    with pytest.raises(CodeIndexError) as excinfo:
        open_index(_db_path(tmp_path))
    assert excinfo.value.code == 10
    assert excinfo.value.kind == "index.vec_extension_unavailable"


def test_fts5_unavailable_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import code_index.storage as storage_mod

    # Patch the compile-option probe to behave as if FTS5 were absent. We
    # cannot rebind sqlite3.Connection.execute (it is a slot), so we replace
    # the helper itself with one that raises the same CodeIndexError the real
    # probe would raise on a build without FTS5.
    def _force_unavailable(conn: sqlite3.Connection) -> None:
        raise CodeIndexError(
            10,
            "index.fts5_unavailable",
            "this SQLite build does not have FTS5 compiled in",
            None,
        )

    monkeypatch.setattr(storage_mod, "_check_fts5_available", _force_unavailable)

    with pytest.raises(CodeIndexError) as excinfo:
        open_index(_db_path(tmp_path))
    assert excinfo.value.code == 10
    assert excinfo.value.kind == "index.fts5_unavailable"
