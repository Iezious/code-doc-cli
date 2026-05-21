"""Graph query layer for ``code_index graph callers|deps``.

Phase 6, step 004. Pure read-only translation from the SQL contract pinned in
``docs/plans/006.sync-symbols-graph/context.md`` ("Symbols / graph SQL
contract") to a small Python API the CLI calls. No plugin or embedding
machinery is involved — given a populated index, this module joins
``edges`` to ``chunks`` and returns :class:`CallerHit` / :class:`DepHit`
rows.

Edge resolution is **lazy** per ``004.context.md``:

- ``query_callers`` matches the user's ``symbol`` argument against
  ``edges.dst_name`` directly; no second join to ``symbols`` is performed,
  and unresolved targets are returned as-is.
- ``query_deps`` returns the raw ``(kind, dst_name, meta)`` tuple from
  ``edges``; ``meta`` is surfaced as the raw JSON string written by the
  plugin, or ``None`` when the column is ``NULL``.

Matching is case-sensitive throughout. Same approach as
:mod:`code_index.symbols` (option a per ``003.context.md`` /
``004.context.md``): the substring branch of :func:`query_callers` sets
``PRAGMA case_sensitive_like = ON;`` on the connection before each query.
The PRAGMA is connection-scoped and idempotent; re-applying on every call
makes the function safe against freshly-opened connections or ones another
caller has already touched.

``graph deps`` does not use ``LIKE`` at all — path matching is exact
equality per decision 4 — so the PRAGMA is not needed on that path. No
globbing, no substring; ``query_deps`` returns ``[]`` for any non-exact
match.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Public result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallerHit:
    """One row returned by :func:`query_callers`.

    Field order matches the JSON shape pinned in ``context.md``
    ("JSON output shapes" -> ``graph callers``):
    ``path``, ``scope``, ``language``, ``start_line``, ``kind``, ``dst_name``.
    """

    path: str
    scope: str | None
    language: str
    start_line: int
    kind: str
    dst_name: str


@dataclass(frozen=True)
class DepHit:
    """One row returned by :func:`query_deps`.

    Field order matches the JSON shape pinned in ``context.md``
    ("JSON output shapes" -> ``graph deps``):
    ``path``, ``kind``, ``dst_name``, ``meta``.

    ``meta`` is the raw JSON string from ``edges.meta`` (or ``None`` when the
    column is ``NULL``). Phase 6 does not parse it; Phase 7's JSON polish may.
    """

    path: str
    kind: str
    dst_name: str
    meta: str | None


# ---------------------------------------------------------------------------
# Query entry points
# ---------------------------------------------------------------------------


def query_callers(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    exact: bool = False,
    language: str | None = None,
) -> list[CallerHit]:
    """Run the ``graph callers`` query against the index.

    :param conn: open connection to the per-project index.
    :param symbol: literal user-supplied symbol name. Matched against
        ``edges.dst_name`` (not against ``symbols.name`` — resolution is
        lazy per ``004.context.md``).
    :param exact: when ``False`` (default), match by case-sensitive substring
        (``SQL LIKE '%symbol%'``); when ``True``, match by exact equality
        (``= ?``). Case-sensitivity is preserved either way.
    :param language: optional canonical language name; when supplied the
        result is narrowed to ``chunks.language = ?``.
    :returns: rows sorted by ``(chunks.path, chunks.start_line)``.

    Empty result returns ``[]`` rather than raising — per ``cli.md``,
    zero results is a success response.
    """
    # PRAGMA is connection-scoped; applying it before every query makes
    # query_callers robust against connections that some other caller opened
    # without the PRAGMA. Idempotent.
    conn.execute("PRAGMA case_sensitive_like = ON")

    op: str
    pattern: str
    if exact:
        op = "="
        pattern = symbol
    else:
        op = "LIKE"
        pattern = f"%{symbol}%"

    sql: str = (
        "SELECT chunks.path, chunks.scope, chunks.language, "
        "chunks.start_line, edges.kind, edges.dst_name "
        "FROM edges "
        "JOIN chunks ON edges.src_chunk_id = chunks.id "
        f"WHERE edges.dst_name {op} ?"
    )
    params: list[object] = [pattern]
    if language is not None:
        sql += " AND chunks.language = ?"
        params.append(language)
    sql += " ORDER BY chunks.path, chunks.start_line"

    hits: list[CallerHit] = []
    for row in conn.execute(sql, params):
        hits.append(
            CallerHit(
                path=str(row[0]),
                scope=None if row[1] is None else str(row[1]),
                language=str(row[2]),
                start_line=int(row[3]),
                kind=str(row[4]),
                dst_name=str(row[5]),
            )
        )
    return hits


def query_deps(
    conn: sqlite3.Connection,
    path: str,
    *,
    language: str | None = None,
) -> list[DepHit]:
    """Run the ``graph deps`` query against the index.

    :param conn: open connection to the per-project index.
    :param path: project-root-relative, forward-slash path. Matched against
        ``chunks.path`` by case-sensitive equality (decision 4 in
        ``context.md``). No globbing, no substring. The engine does not
        normalize the input — see ``004.context.md`` "Path normalization on
        input".
    :param language: optional canonical language name; when supplied the
        result is narrowed to ``chunks.language = ?``.
    :returns: rows sorted by ``(chunks.path, edges.kind, edges.dst_name)``.
        Includes both resolved and unresolved ``dst_name`` values (the
        contract allows unresolved per ``storage.md`` "Edge resolution").

    Empty result returns ``[]`` rather than raising.
    """
    sql: str = (
        "SELECT chunks.path, edges.kind, edges.dst_name, edges.meta "
        "FROM edges "
        "JOIN chunks ON edges.src_chunk_id = chunks.id "
        "WHERE chunks.path = ?"
    )
    params: list[object] = [path]
    if language is not None:
        sql += " AND chunks.language = ?"
        params.append(language)
    sql += " ORDER BY chunks.path, edges.kind, edges.dst_name"

    hits: list[DepHit] = []
    for row in conn.execute(sql, params):
        hits.append(
            DepHit(
                path=str(row[0]),
                kind=str(row[1]),
                dst_name=str(row[2]),
                meta=None if row[3] is None else str(row[3]),
            )
        )
    return hits


__all__ = ["CallerHit", "DepHit", "query_callers", "query_deps"]
