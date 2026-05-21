"""Symbols query layer for ``code_index symbols defs|refs``.

Phase 6, step 003. Pure read-only translation from the SQL contract pinned in
``docs/plans/006.sync-symbols-graph/context.md`` ("Symbols / graph SQL
contract") to a small Python API the CLI calls. No plugin or embedding
machinery is involved — given a populated index, this module joins
``symbols`` to ``chunks`` and returns :class:`SymbolHit` rows.

Matching is case-sensitive throughout. This module obtains case-sensitive
``LIKE`` by setting ``PRAGMA case_sensitive_like = ON;`` on the connection at
query time per ``003.context.md`` (option a). The PRAGMA is connection-scoped
and does not leak out of this read path; it is re-applied on every
:func:`query_symbols` call so the function is safe to use against a freshly
opened connection or one that another caller has already touched.

LIKE wildcard escaping: per ``003.context.md``, the polyglot fixture has no
symbol names containing ``%`` or ``_`` and this is treated as a robustness
nicety rather than a contract requirement. Phase 6 skips the escape for MVP;
if a future plugin starts emitting names with SQL-wildcard characters the
substring branch will need an ``ESCAPE`` clause (see the per-step context).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolHit:
    """One row returned by :func:`query_symbols`.

    Field order matches the JSON shape pinned in ``context.md``
    ("JSON output shapes" → ``symbols defs`` / ``symbols refs``):
    ``path``, ``scope``, ``language``, ``name``, ``line``.
    """

    path: str
    scope: str | None
    language: str
    name: str
    line: int


# ---------------------------------------------------------------------------
# Query entry point
# ---------------------------------------------------------------------------


def query_symbols(
    conn: sqlite3.Connection,
    name: str,
    *,
    kind: str,
    exact: bool = False,
    language: str | None = None,
) -> list[SymbolHit]:
    """Run the ``symbols defs|refs`` query against the index.

    :param conn: open connection to the per-project index.
    :param name: literal user-supplied symbol name.
    :param kind: ``"def"`` for ``symbols defs``; ``"ref"`` for ``symbols refs``.
    :param exact: when ``False`` (default), match by case-sensitive substring
        (``SQL LIKE '%name%'``); when ``True``, match by exact equality
        (``= ?``). Case-sensitivity is preserved either way.
    :param language: optional canonical language name; when supplied the
        result is narrowed to ``chunks.language = ?``.
    :returns: rows sorted by ``(chunks.path, symbols.line)``.

    Empty result returns ``[]`` rather than raising — per ``cli.md``,
    zero results is a success response.
    """
    # PRAGMA is connection-scoped; applying it before every query makes
    # query_symbols robust against connections that some other caller opened
    # without the PRAGMA. Idempotent.
    conn.execute("PRAGMA case_sensitive_like = ON")

    op: str
    pattern: str
    if exact:
        op = "="
        pattern = name
    else:
        op = "LIKE"
        pattern = f"%{name}%"

    sql: str = (
        "SELECT chunks.path, chunks.scope, chunks.language, "
        "symbols.name, symbols.line "
        "FROM symbols "
        "JOIN chunks ON symbols.chunk_id = chunks.id "
        f"WHERE symbols.kind = ? AND symbols.name {op} ?"
    )
    params: list[object] = [kind, pattern]
    if language is not None:
        sql += " AND chunks.language = ?"
        params.append(language)
    sql += " ORDER BY chunks.path, symbols.line"

    hits: list[SymbolHit] = []
    for row in conn.execute(sql, params):
        hits.append(
            SymbolHit(
                path=str(row[0]),
                scope=None if row[1] is None else str(row[1]),
                language=str(row[2]),
                name=str(row[3]),
                line=int(row[4]),
            )
        )
    return hits


__all__ = ["SymbolHit", "query_symbols"]
