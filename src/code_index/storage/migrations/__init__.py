"""Forward-only file-per-step migrations harness.

Each migration is a module named ``<from>_to_<to>.py`` in this package and
exposes three names: ``from_version: str``, ``to_version: str``, and
``apply(conn: sqlite3.Connection) -> None``. The runner discovers migrations
by filename, sorts them numerically by ``from_version``, and applies each in
its own transaction, advancing ``meta.schema_version`` after every successful
apply.

The first migration ``0_to_1.py`` is the schema-from-scratch path. There is
no separate "create schema" code path.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from typing import Protocol, cast, runtime_checkable

_MIGRATION_FILENAME_RE = re.compile(r"^(\d+)_to_(\d+)$")


@runtime_checkable
class Migration(Protocol):
    """Structural type satisfied by every ``<from>_to_<to>.py`` module."""

    from_version: str
    to_version: str

    def apply(self, conn: sqlite3.Connection) -> None: ...


def discover_migrations() -> list[Migration]:
    """Return every ``<from>_to_<to>.py`` migration in this package.

    Discovery uses :func:`pkgutil.iter_modules` on this package. Modules
    whose names do not match ``<int>_to_<int>`` are ignored (including
    ``__init__``). The list is sorted numerically by ``from_version``.
    """
    migrations: list[tuple[int, Migration]] = []
    for module_info in pkgutil.iter_modules(__path__):
        match = _MIGRATION_FILENAME_RE.match(module_info.name)
        if match is None:
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        migration = cast(Migration, module)
        migrations.append((int(match.group(1)), migration))

    migrations.sort(key=lambda item: item[0])
    return [migration for _, migration in migrations]


def _current_schema_version(conn: sqlite3.Connection) -> str:
    """Return the persisted ``meta.schema_version``, or ``"0"`` if absent.

    "Absent" covers both a brand-new database (no ``meta`` table yet) and a
    database that has the ``meta`` table but no ``schema_version`` row.
    """
    try:
        cursor = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    except sqlite3.OperationalError:
        return "0"
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return "0"
    return str(row[0])


def run_migrations(conn: sqlite3.Connection, target_version: str) -> None:
    """Walk migrations forward until ``meta.schema_version == target_version``.

    Starts from the current ``meta.schema_version`` (or ``"0"`` when the row
    is absent). Each migration runs inside its own transaction; the row in
    ``meta`` is updated to the migration's ``to_version`` as part of the same
    transaction. No-op if the database is already at ``target_version``.
    """
    migrations = discover_migrations()
    by_from: dict[str, Migration] = {m.from_version: m for m in migrations}

    current = _current_schema_version(conn)
    while current != target_version:
        migration = by_from.get(current)
        if migration is None:
            raise RuntimeError(
                f"no migration registered from schema_version {current!r} "
                f"toward {target_version!r}"
            )
        with conn:
            migration.apply(conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (migration.to_version,),
            )
        current = migration.to_version


__all__ = ["Migration", "discover_migrations", "run_migrations"]
