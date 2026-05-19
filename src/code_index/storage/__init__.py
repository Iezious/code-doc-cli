"""Storage layer — SQLite open helper, schema-version check, migrations entry.

The index is a single SQLite file per project with the sqlite-vec extension
loaded and FTS5 compiled in. Both extension availability and schema version
are checked at open time, not at first query; failure raises
:class:`code_index.errors.CodeIndexError` with the documented ``kind``.

The first migration ``0_to_1.py`` is the schema-from-scratch path. There is
no separate "create schema" code; migrations are the single source of truth
for schema. See ``docs/architecture/storage.md``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from code_index.errors import (
    EXIT_INDEX_SCHEMA,
    CodeIndexError,
    Kinds,
)

CURRENT_SCHEMA_VERSION: str = "1"


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec loadable extension on ``conn``.

    Translates any import or load failure into ``CodeIndexError`` with
    ``kind=index.vec_extension_unavailable`` and ``code=10``. The underlying
    exception message is preserved under ``detail["cause"]``.
    """
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
    except Exception as exc:  # noqa: BLE001 - intentional broad translation
        raise CodeIndexError(
            EXIT_INDEX_SCHEMA,
            Kinds.INDEX_VEC_EXTENSION_UNAVAILABLE,
            "sqlite-vec extension could not be loaded",
            {"cause": str(exc)},
        ) from exc


def _check_fts5_available(conn: sqlite3.Connection) -> None:
    """Confirm FTS5 is compiled into the running SQLite build.

    Uses ``sqlite_compileoption_used('ENABLE_FTS5')`` as the cheap probe
    (no virtual table created). Returns silently when available; raises
    ``CodeIndexError`` with ``kind=index.fts5_unavailable`` and ``code=10``
    otherwise.
    """
    row = conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()
    available: bool = bool(row and row[0])
    if not available:
        raise CodeIndexError(
            EXIT_INDEX_SCHEMA,
            Kinds.INDEX_FTS5_UNAVAILABLE,
            "this SQLite build does not have FTS5 compiled in",
            None,
        )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Return ``meta.value`` for ``key`` or ``None`` if absent."""
    cursor = conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row is None:
        return None
    value = row[0]
    return None if value is None else str(value)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert ``meta.value`` for ``key``."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def open_index(
    db_path: Path,
    *,
    create_if_missing: bool = True,
    check_version: bool = True,
) -> sqlite3.Connection:
    """Open the index at ``db_path``.

    Behavior:

    - Opens the sqlite3 connection.
    - Sets ``PRAGMA journal_mode = WAL``.
    - Enables extension loading and loads sqlite-vec; failure raises
      ``CodeIndexError(EXIT_INDEX_SCHEMA, Kinds.INDEX_VEC_EXTENSION_UNAVAILABLE)``.
    - Probes FTS5 via ``sqlite_compileoption_used('ENABLE_FTS5')``; failure
      raises ``CodeIndexError(EXIT_INDEX_SCHEMA, Kinds.INDEX_FTS5_UNAVAILABLE)``.
    - If ``create_if_missing`` and the file did not exist, runs all migrations
      from ``"0"`` to ``CURRENT_SCHEMA_VERSION`` and writes
      ``meta.code_index_version``.
    - If ``check_version`` and a ``meta.schema_version`` row exists with a
      value different from ``CURRENT_SCHEMA_VERSION``, raises
      ``CodeIndexError(EXIT_INDEX_SCHEMA, Kinds.INDEX_SCHEMA_MISMATCH)``.

    Returns the open connection. Caller owns closing it.
    """
    existed: bool = db_path.exists()
    if not existed and not create_if_missing:
        raise CodeIndexError(
            EXIT_INDEX_SCHEMA,
            Kinds.INDEX_MISSING,
            f"index file does not exist: {db_path.as_posix()}",
            {"path": db_path.as_posix()},
        )

    if not existed:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        _load_sqlite_vec(conn)
        _check_fts5_available(conn)

        # Local import to avoid a circular import at module load time.
        from code_index.storage.migrations import run_migrations

        if not existed:
            run_migrations(conn, CURRENT_SCHEMA_VERSION)
        elif check_version:
            current = get_meta(conn, "schema_version")
            if current is not None and current != CURRENT_SCHEMA_VERSION:
                raise CodeIndexError(
                    EXIT_INDEX_SCHEMA,
                    Kinds.INDEX_SCHEMA_MISMATCH,
                    (
                        f"index schema_version is {current!r}, "
                        f"engine expects {CURRENT_SCHEMA_VERSION!r}"
                    ),
                    {
                        "found": current,
                        "expected": CURRENT_SCHEMA_VERSION,
                    },
                )
    except Exception:
        conn.close()
        raise

    return conn


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "get_meta",
    "open_index",
    "set_meta",
]
