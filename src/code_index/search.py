"""Hybrid BM25 + dense retrieval pipeline.

Owns the query-time path: BM25 over the FTS5 ``chunks_fts`` mirror, dense
nearest-neighbour over the ``sqlite-vec`` ``embeddings`` table, and
Reciprocal Rank Fusion (k = 60) over the two candidate pools. Filters
(``--lang``, ``--kind``, ``--path``) are applied via SQL ``WHERE`` to
both candidate queries before fusion, per
``docs/architecture/retrieval.md``.

The module exposes a single public entry point :func:`search` plus the
:class:`SearchResult` / :class:`SearchFilters` row shapes used by the CLI
layer (Phase 5 step 002) and any future programmatic consumer.

The embedding-compatibility check lives in :mod:`code_index.storage`
(``verify_index_compat``); :func:`search` itself is loud-fail-agnostic and
just consumes whatever backend the caller hands it (or ``None`` for
BM25-only mode).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np

from code_index.embeddings import EmbeddingBackend

Mode = Literal["bm25", "dense", "hybrid"]

RRF_K: Final[int] = 60
"""Reciprocal Rank Fusion constant. Pinned by ``retrieval.md``; not configurable."""

EXCERPT_MAX_LINES: Final[int] = 30
"""Maximum lines of ``chunks.content`` returned in ``SearchResult.excerpt``."""


@dataclass(frozen=True)
class SearchResult:
    """One row of search output.

    ``score`` is the fused RRF score under ``mode == "hybrid"`` and the
    single-pool contribution (``1 / (RRF_K + rank)``) under ``"bm25"`` or
    ``"dense"``. ``excerpt`` is the first :data:`EXCERPT_MAX_LINES` lines
    of ``chunks.content``.
    """

    path: str
    start_line: int
    end_line: int
    language: str
    kind: str
    name: str | None
    scope: str | None
    excerpt: str
    score: float


@dataclass(frozen=True)
class SearchFilters:
    """Optional filters applied to both candidate pools before fusion.

    Each field is an opaque string; validation against the language
    registry (``--lang``) is the CLI layer's job. A ``None`` field means
    "no filter on this column".
    """

    lang: str | None = None
    kind: str | None = None
    path_glob: str | None = None


_NO_FILTERS: Final[SearchFilters] = SearchFilters()


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    backend: EmbeddingBackend | None,
    mode: Mode = "hybrid",
    k: int = 20,
    bm25_k: int = 100,
    dense_k: int = 100,
    filters: SearchFilters = _NO_FILTERS,
) -> list[SearchResult]:
    """Run a search against the open index ``conn``.

    - ``mode == "bm25"``: BM25 only; ``backend`` may be ``None``.
    - ``mode == "dense"``: dense only; ``backend`` is required.
    - ``mode == "hybrid"``: both pools fused via RRF; ``backend`` is required.

    Filters are applied via SQL ``WHERE`` on both candidate queries before
    fusion. Returns at most ``k`` results ordered by descending fused
    score. Returning ``[]`` is valid; it is not an error.

    Raises :class:`ValueError` when ``mode`` is ``"dense"`` or ``"hybrid"``
    and ``backend`` is ``None``. The CLI layer turns this into a
    ``CodeIndexError`` envelope; here we keep the signature pure and let
    the boundary translate.
    """
    if mode in ("dense", "hybrid") and backend is None:
        raise ValueError(
            f"mode={mode!r} requires a non-None embedding backend"
        )

    bm25_pool: list[tuple[int, int]] = []
    dense_pool: list[tuple[int, int]] = []

    if mode in ("bm25", "hybrid"):
        bm25_pool = _bm25_candidates(
            conn, query, limit=bm25_k, filters=filters
        )

    if mode in ("dense", "hybrid"):
        assert backend is not None  # narrowed by the early raise above
        vectors = backend.encode([query])
        query_vector = np.asarray(vectors[0], dtype=np.float32)
        dense_pool = _dense_candidates(
            conn, query_vector, limit=dense_k, filters=filters
        )

    if mode == "bm25":
        scored = _single_pool_scores(bm25_pool)
    elif mode == "dense":
        scored = _single_pool_scores(dense_pool)
    else:
        scored = _rrf_fuse(bm25_pool, dense_pool)

    return _hydrate(conn, scored, k=k)


def _bm25_candidates(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    filters: SearchFilters,
) -> list[tuple[int, int]]:
    """Return ``(chunk_id, rank)`` pairs from FTS5 BM25.

    ``rank`` starts at 1 for the top-scoring row. Filters are applied as
    ``WHERE`` predicates over the joined ``chunks`` row, before ordering
    by ``bm25(chunks_fts)``.
    """
    sql_parts: list[str] = [
        "SELECT c.id",
        "FROM chunks_fts f JOIN chunks c ON c.id = f.rowid",
        "WHERE chunks_fts MATCH ?",
    ]
    params: list[object] = [query]
    _append_filter_clauses(sql_parts, params, filters)
    sql_parts.append("ORDER BY bm25(chunks_fts)")
    sql_parts.append("LIMIT ?")
    params.append(limit)

    sql = "\n".join(sql_parts)
    rows = conn.execute(sql, params).fetchall()
    return [(int(row[0]), index + 1) for index, row in enumerate(rows)]


def _dense_candidates(
    conn: sqlite3.Connection,
    query_vector: np.ndarray,
    *,
    limit: int,
    filters: SearchFilters,
) -> list[tuple[int, int]]:
    """Return ``(chunk_id, rank)`` pairs from sqlite-vec KNN.

    ``rank`` starts at 1 for the nearest row. The query vector is
    serialized to ``float32`` bytes per the sqlite-vec MATCH contract.
    Filters are applied as additional ``WHERE`` predicates over the joined
    ``chunks`` row, alongside the ``MATCH`` constraint and the ``k = ?``
    constraint that sqlite-vec requires.
    """
    qvec_bytes: bytes = np.asarray(query_vector, dtype=np.float32).tobytes()
    sql_parts: list[str] = [
        "SELECT e.chunk_id",
        "FROM embeddings e JOIN chunks c ON c.id = e.chunk_id",
        "WHERE e.embedding MATCH ?",
        "AND k = ?",
    ]
    params: list[object] = [qvec_bytes, limit]
    _append_filter_clauses(sql_parts, params, filters)
    sql_parts.append("ORDER BY e.distance")

    sql = "\n".join(sql_parts)
    rows = conn.execute(sql, params).fetchall()
    return [(int(row[0]), index + 1) for index, row in enumerate(rows)]


def _append_filter_clauses(
    sql_parts: list[str],
    params: list[object],
    filters: SearchFilters,
) -> None:
    """Append parameterized ``AND c.<col> ...`` clauses for each active filter.

    Mutates ``sql_parts`` and ``params`` in place. No string interpolation
    of user values; every filter is a bound parameter.
    """
    if filters.lang is not None:
        sql_parts.append("AND c.language = ?")
        params.append(filters.lang)
    if filters.kind is not None:
        sql_parts.append("AND c.kind = ?")
        params.append(filters.kind)
    if filters.path_glob is not None:
        sql_parts.append("AND c.path GLOB ?")
        params.append(filters.path_glob)


def _single_pool_scores(
    pool: list[tuple[int, int]],
) -> list[tuple[int, float]]:
    """Score a single-mode candidate pool with the RRF contribution term.

    Under ``mode == "bm25"`` or ``"dense"`` we still want a numeric score
    on each :class:`SearchResult`. The natural choice is the same
    ``1 / (RRF_K + rank)`` term that hybrid mode would have contributed;
    that keeps the score field meaningful and monotonic in the original
    rank without exposing raw BM25 or cosine distance to callers.

    Result order is preserved (the input pool is already in rank order).
    """
    return [
        (chunk_id, 1.0 / (RRF_K + rank))
        for chunk_id, rank in pool
    ]


def _rrf_fuse(
    bm25: list[tuple[int, int]],
    dense: list[tuple[int, int]],
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion with ``k = RRF_K``.

    Returns ``(chunk_id, fused_score)`` pairs sorted by ``fused_score``
    descending. Items present in only one pool contribute that pool's
    term only.

    Tie-break: when two items have equal fused scores (within float
    tolerance), the item with the lower dense-rank wins; items absent
    from the dense pool sort after items present in it on ties.
    """
    bm25_rank: dict[int, int] = {chunk_id: rank for chunk_id, rank in bm25}
    dense_rank: dict[int, int] = {chunk_id: rank for chunk_id, rank in dense}

    all_ids: set[int] = set(bm25_rank) | set(dense_rank)

    scored: list[tuple[int, float]] = []
    for chunk_id in all_ids:
        score = 0.0
        if chunk_id in bm25_rank:
            score += 1.0 / (RRF_K + bm25_rank[chunk_id])
        if chunk_id in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[chunk_id])
        scored.append((chunk_id, score))

    # The "infinity" sentinel sorts absent items last on the tie-break key
    # without affecting items that appear in the dense pool.
    def sort_key(item: tuple[int, float]) -> tuple[float, float]:
        chunk_id, score = item
        dense_position: float = float(dense_rank.get(chunk_id, float("inf")))
        # Sort by descending score (negate) then ascending dense rank.
        return (-score, dense_position)

    scored.sort(key=sort_key)
    return scored


def _hydrate(
    conn: sqlite3.Connection,
    scored: list[tuple[int, float]],
    *,
    k: int,
) -> list[SearchResult]:
    """Look up the top-``k`` chunk rows by id and build :class:`SearchResult`.

    Preserves the input ``scored`` order. Chunks whose id is missing from
    ``chunks`` (e.g. due to a race with index rebuild) are skipped
    silently; we just return fewer rows than requested.
    """
    if not scored:
        return []

    top = scored[:k]
    ids = [chunk_id for chunk_id, _ in top]
    score_by_id: dict[int, float] = {cid: s for cid, s in top}

    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, path, language, start_line, end_line, "  # noqa: S608 - placeholders only
        f"       kind, name, scope, content "
        f"FROM chunks WHERE id IN ({placeholders})",
        ids,
    ).fetchall()

    by_id: dict[int, sqlite3.Row | tuple[object, ...]] = {}
    for row in rows:
        row_id_raw: object = row[0]
        assert isinstance(row_id_raw, int)
        by_id[row_id_raw] = row

    results: list[SearchResult] = []
    for chunk_id in ids:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        path_val: object = row[1]
        language_val: object = row[2]
        start_val: object = row[3]
        end_val: object = row[4]
        kind_val: object = row[5]
        name_val: object = row[6]
        scope_val: object = row[7]
        content_val: object = row[8]
        assert isinstance(path_val, str)
        assert isinstance(language_val, str)
        assert isinstance(start_val, int)
        assert isinstance(end_val, int)
        assert isinstance(kind_val, str)
        assert name_val is None or isinstance(name_val, str)
        assert scope_val is None or isinstance(scope_val, str)
        content = "" if content_val is None else str(content_val)
        excerpt = "\n".join(content.splitlines()[:EXCERPT_MAX_LINES])
        results.append(
            SearchResult(
                path=path_val,
                start_line=start_val,
                end_line=end_val,
                language=language_val,
                kind=kind_val,
                name=name_val,
                scope=scope_val,
                excerpt=excerpt,
                score=score_by_id[chunk_id],
            )
        )
    return results


__all__ = [
    "EXCERPT_MAX_LINES",
    "RRF_K",
    "Mode",
    "SearchFilters",
    "SearchResult",
    "search",
]
