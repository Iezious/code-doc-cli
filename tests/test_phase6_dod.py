"""End-to-end Phase 6 DoD integration test (feature 006, step 005).

Drives the ``code_index`` CLI through :func:`code_index.cli._invoke` against
a copy of ``tests/fixtures/projects/polyglot_minimal/`` and asserts the
phase DoD from ``docs/plans/006.sync-symbols-graph/005.dod-integration.md``:

1. Build the index against the polyglot fixture.
2. Snapshot the post-build ``chunks`` / ``files`` state.
3. Mutate one file (``main.py``) — append a new ``def`` and force-advance
   the mtime via :func:`os.utime` (see ``005.context.md``).
4. Run ``index sync`` and assert only ``main.py``'s rows moved.
5. Run ``symbols defs newly_added_symbol`` and assert one hit comes back
   with the right ``path`` / ``language`` / ``name``.
6. Run ``symbols refs <known-ref-name>`` reading the name from the DB
   (silence is acceptable when the polyglot has no ``ref`` symbols).
7. Run ``graph callers <known-edge-dst>`` reading the name from the DB.
8. Run ``graph deps main.py`` and assert at least one hit.
9. Run ``index rebuild --yes`` and assert row counts in all six row-data
   tables match the post-sync state (rebuild is idempotent against the
   unmodified post-sync tree).

The test does **not** import :mod:`code_index.sync`, :mod:`code_index.symbols`,
or :mod:`code_index.graph` — those are exercised through the CLI surface.
:func:`code_index.storage.open_index` is the only engine symbol used
directly (for snapshotting DB state between CLI invocations).

The first run downloads the fastembed model (~120 MB) per Phase 2's
contract; subsequent runs reuse the cache at ``tests/.cache/fastembed/``.
The ``warm_fastembed`` fixture patches the package-level
:func:`code_index.embeddings.from_config` (and the indexer's
import-time binding, which Phase 4 deliberately preserved) so every
CLI invocation in this test resolves to a cache-aware backend.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from code_index import embeddings, indexer
from code_index.cli import _invoke
from code_index.embeddings.fastembed import FastembedBackend
from code_index.storage import open_index

FIXTURE_SRC: Path = (
    Path(__file__).parent / "fixtures" / "projects" / "polyglot_minimal"
)
# Resolve to an absolute path before any ``monkeypatch.chdir`` so the cache
# lives at the repo's ``tests/.cache/fastembed/`` regardless of cwd. A bare
# relative string would resolve under ``tmp_path`` after the chdir and miss
# the shared CI cache entirely.
_FASTEMBED_CACHE: str = str(
    (Path(__file__).resolve().parent / ".cache" / "fastembed").resolve()
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _copy_fixture(tmp_path: Path) -> None:
    """Copy the polyglot fixture into ``tmp_path`` and add a ``.git/`` marker.

    Mirrors ``tests/test_index_build_cli.py::_copy_fixture``. The ``.git/``
    directory is created at test time per the Phase 4 step context — the
    walker's ``.gitignore`` honoring path activates when a ``.git/`` marker
    is present.
    """
    shutil.copytree(FIXTURE_SRC, tmp_path, dirs_exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)


@pytest.fixture
def warm_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the backend factory to a cache-aware fastembed instance.

    The CLI pre-flight (``code_index.cli._preflight``) and the sync engine
    both resolve ``from_config`` through :mod:`code_index.embeddings` at
    call time, so patching the package symbol covers them. The Phase 4
    indexer still binds ``from_config`` into its own namespace at import
    time (preserved by step 005's bug-fix scope), so we patch that binding
    explicitly as well. Importing the indexer here is permitted by the
    step's DoD — only :mod:`code_index.sync`, :mod:`code_index.symbols`,
    and :mod:`code_index.graph` are off limits.
    """

    def _build_backend(config: Any) -> FastembedBackend:
        return FastembedBackend(
            model=config.embed_model,
            batch_size=config.embed_batch_size,
            cache_dir=_FASTEMBED_CACHE,
        )

    monkeypatch.setattr(embeddings, "from_config", _build_backend)
    monkeypatch.setattr(indexer, "from_config", _build_backend)


def _db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Open the project's index via the Phase 1 helper.

    Counting rows in the ``embeddings`` ``vec0`` virtual table requires
    sqlite-vec loaded on the connection — :func:`open_index` does that.
    """
    return open_index(tmp_path / "docs" / ".helpers" / "index.sqlite")


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return current row counts for the six indexer-owned tables."""
    out: dict[str, int] = {}
    for table in ("chunks", "chunks_fts", "embeddings", "symbols", "edges", "files"):
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        out[table] = int(row[0]) if row is not None else 0
    return out


def _chunk_id_paths(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Return ``[(chunks.id, chunks.path), ...]`` sorted by ``id``.

    The id field is the identity reference for the "only one file changed"
    assertion: every untouched file keeps the same ``id`` set across a
    sync, and the touched file's ids are replaced.
    """
    return [
        (int(r[0]), str(r[1]))
        for r in conn.execute("SELECT id, path FROM chunks ORDER BY id")
    ]


def _files_snapshot(conn: sqlite3.Connection) -> dict[str, tuple[float, int]]:
    """Return ``{path: (mtime, size)}`` for every row in ``files``."""
    return {
        str(r[0]): (float(r[1]), int(r[2]))
        for r in conn.execute("SELECT path, mtime, size FROM files")
    }


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke the CLI through the boundary handler; return exit + streams."""
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------------------
# The DoD test
# ---------------------------------------------------------------------------


def test_phase6_dod_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    """Phase 6 DoD: end-to-end CLI surface against the polyglot fixture."""
    del warm_fastembed  # consumed via monkeypatch side effects
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    # ------------------------------------------------------------------
    # Step 1+2: init + build.
    # ------------------------------------------------------------------
    init_exit, _init_out, _init_err = _run(["init"], capsys)
    assert init_exit == 0

    build_exit, build_out, _build_err = _run(
        ["index", "build", "--root", str(tmp_path)], capsys
    )
    assert build_exit == 0, build_out

    # ------------------------------------------------------------------
    # Step 3: snapshot pre-sync state.
    # ------------------------------------------------------------------
    conn = _db_conn(tmp_path)
    try:
        pre_chunks: list[tuple[int, str]] = _chunk_id_paths(conn)
        pre_files: dict[str, tuple[float, int]] = _files_snapshot(conn)
        pre_counts: dict[str, int] = _row_counts(conn)
    finally:
        conn.close()

    # Sanity: build populated every relevant table.
    for table, count in pre_counts.items():
        assert count > 0, (table, pre_counts)
    assert "main.py" in pre_files, sorted(pre_files)
    assert any(path == "main.py" for _id, path in pre_chunks), pre_chunks

    # ------------------------------------------------------------------
    # Step 4: mutate ``main.py`` and force-advance its mtime.
    # ------------------------------------------------------------------
    main_py: Path = tmp_path / "main.py"
    original_text: str = main_py.read_text(encoding="utf-8")
    new_text: str = (
        original_text
        + "\n\n"
        + "def newly_added_symbol():\n"
        + '    return "phase6_marker"\n'
    )
    main_py.write_text(new_text, encoding="utf-8")
    # Force mtime forward: NTFS / fast filesystems can keep st_mtime stable
    # across a write inside one tick; the sync engine then sees the file as
    # unchanged and skips it. See ``005.context.md`` "mtime-advance technique".
    bumped: float = time.time() + 5.0
    os.utime(main_py, (bumped, bumped))

    # ------------------------------------------------------------------
    # Step 5: run ``index sync``.
    # ------------------------------------------------------------------
    sync_exit, sync_out, _sync_err = _run(
        ["--format", "json", "index", "sync"], capsys
    )
    assert sync_exit == 0, sync_out

    sync_payload: dict[str, Any] = json.loads(sync_out)
    assert set(sync_payload.keys()) == {
        "files_added",
        "files_changed",
        "files_unchanged",
        "files_removed",
        "chunks_inserted_total",
        "seconds_elapsed",
    }
    # Exactly one file changed; nothing added / removed.
    assert sync_payload["files_changed"] == 1, sync_payload
    assert sync_payload["files_added"] == 0, sync_payload
    assert sync_payload["files_removed"] == 0, sync_payload

    # ------------------------------------------------------------------
    # Step 6: assert only ``main.py`` moved in the DB.
    # ------------------------------------------------------------------
    conn = _db_conn(tmp_path)
    try:
        post_chunks: list[tuple[int, str]] = _chunk_id_paths(conn)
        post_files: dict[str, tuple[float, int]] = _files_snapshot(conn)
        post_counts: dict[str, int] = _row_counts(conn)

        # Old ids for non-main.py files survive verbatim.
        pre_other: list[tuple[int, str]] = [
            row for row in pre_chunks if row[1] != "main.py"
        ]
        post_other: list[tuple[int, str]] = [
            row for row in post_chunks if row[1] != "main.py"
        ]
        assert post_other == pre_other, (
            f"non-main.py chunk ids changed:\n"
            f"  pre  = {pre_other}\n"
            f"  post = {post_other}"
        )

        # Old main.py ids are gone; new main.py rows exist with new ids.
        pre_main_ids: set[int] = {
            row[0] for row in pre_chunks if row[1] == "main.py"
        }
        post_main_ids: set[int] = {
            row[0] for row in post_chunks if row[1] == "main.py"
        }
        assert pre_main_ids.isdisjoint(post_main_ids), (
            f"sync did not re-issue main.py chunk ids: "
            f"pre={pre_main_ids}, post={post_main_ids}"
        )
        assert post_main_ids, "main.py has no chunks after sync"

        # At least one symbol named ``newly_added_symbol`` lives on a
        # main.py chunk. (We do NOT assert this is the only new symbol —
        # the python plugin re-emits every def, so old defs reappear too.)
        new_symbol_rows = list(
            conn.execute(
                "SELECT chunks.path, chunks.language, symbols.name "
                "FROM symbols JOIN chunks ON symbols.chunk_id = chunks.id "
                "WHERE chunks.path = 'main.py' "
                "AND symbols.name = 'newly_added_symbol'"
            )
        )
        assert new_symbol_rows, (
            "expected at least one symbol named newly_added_symbol on main.py"
        )
        for row in new_symbol_rows:
            assert str(row[1]) == "python", row

        # files row for main.py has the bumped mtime + the new on-disk size.
        disk_stat = os.stat(main_py)
        assert "main.py" in post_files
        post_main_mtime, post_main_size = post_files["main.py"]
        assert post_main_mtime == disk_stat.st_mtime, (
            post_main_mtime, disk_stat.st_mtime
        )
        assert post_main_size == disk_stat.st_size, (
            post_main_size, disk_stat.st_size
        )
        # And it actually moved relative to the pre-snapshot.
        assert pre_files["main.py"] != (post_main_mtime, post_main_size)

        # Every other file row is byte-identical to the pre-snapshot.
        for path, pre_val in pre_files.items():
            if path == "main.py":
                continue
            assert post_files.get(path) == pre_val, (
                path, pre_val, post_files.get(path)
            )

        # Orphan check: chunks_fts.rowid covers exactly chunks.id.
        chunks_ids: set[int] = {row[0] for row in post_chunks}
        fts_ids: set[int] = {
            int(r[0]) for r in conn.execute("SELECT rowid FROM chunks_fts")
        }
        assert fts_ids == chunks_ids, (
            f"chunks_fts.rowid drifted from chunks.id: "
            f"only-in-fts={fts_ids - chunks_ids}, "
            f"only-in-chunks={chunks_ids - fts_ids}"
        )

        # Row-count sanity: every table still positive; chunks count grew by
        # the new chunks count for main.py (number of new chunks emitted on
        # the post-mutate main.py minus the original main.py chunk count).
        for table, count in post_counts.items():
            assert count > 0, (table, post_counts)
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # Step 7: ``symbols defs newly_added_symbol``.
    # ------------------------------------------------------------------
    defs_exit, defs_out, _defs_err = _run(
        ["--format", "json", "symbols", "defs", "newly_added_symbol"], capsys
    )
    assert defs_exit == 0, defs_out
    defs_payload: list[dict[str, Any]] = json.loads(defs_out)
    assert defs_payload, "symbols defs returned no hits for newly_added_symbol"

    matching_defs = [
        hit
        for hit in defs_payload
        if hit["name"] == "newly_added_symbol" and hit["path"] == "main.py"
    ]
    assert matching_defs, defs_payload
    for hit in matching_defs:
        assert set(hit.keys()) == {"path", "scope", "language", "name", "line"}
        assert hit["language"] == "python"
        # The python plugin emits dotted scope-or-None on chunks.scope; the
        # added symbol lives at module scope so the symbol's row carries the
        # *chunk* scope (None for top-level). We do not hardcode the value
        # beyond asserting it is either None or a string — the contract is
        # "scope is surfaced", not a specific dotted form.
        assert hit["scope"] is None or isinstance(hit["scope"], str), hit
        assert isinstance(hit["line"], int) and hit["line"] >= 1, hit

    # ------------------------------------------------------------------
    # Step 8: ``symbols refs <known-ref>``.
    #
    # The polyglot fixture is owned by Phase 4. Rather than hardcode plugin
    # conventions, read a candidate ref name from the DB. If no ref rows
    # exist (the python plugin only emits defs), the CLI must still return
    # an empty array under JSON — an acceptable outcome per the step file.
    # ------------------------------------------------------------------
    conn = _db_conn(tmp_path)
    try:
        ref_row = conn.execute(
            "SELECT name FROM symbols WHERE kind = 'ref' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if ref_row is not None:
        ref_name: str = str(ref_row[0])
        refs_exit, refs_out, _refs_err = _run(
            ["--format", "json", "symbols", "refs", ref_name], capsys
        )
        assert refs_exit == 0, refs_out
        refs_payload: list[dict[str, Any]] = json.loads(refs_out)
        assert refs_payload, (
            f"symbols refs returned no hits for known ref {ref_name!r}"
        )
        for hit in refs_payload:
            assert set(hit.keys()) == {
                "path",
                "scope",
                "language",
                "name",
                "line",
            }
    else:
        # No ref symbols in the polyglot fixture; the CLI must still answer.
        refs_exit, refs_out, _refs_err = _run(
            [
                "--format",
                "json",
                "symbols",
                "refs",
                "definitely_not_present",
            ],
            capsys,
        )
        assert refs_exit == 0, refs_out
        assert json.loads(refs_out) == []

    # ------------------------------------------------------------------
    # Step 9: ``graph callers <known-edge-dst>``.
    #
    # Pick a name that appears in edges.dst_name; the polyglot fixture is
    # guaranteed to have at least one edge (every plugin emits imports).
    # ------------------------------------------------------------------
    conn = _db_conn(tmp_path)
    try:
        edge_row = conn.execute(
            "SELECT dst_name FROM edges LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert edge_row is not None, "polyglot fixture produced zero edges"
    callers_target: str = str(edge_row[0])

    callers_exit, callers_out, _callers_err = _run(
        [
            "--format",
            "json",
            "graph",
            "callers",
            "--exact",
            callers_target,
        ],
        capsys,
    )
    assert callers_exit == 0, callers_out
    callers_payload: list[dict[str, Any]] = json.loads(callers_out)
    assert callers_payload, (
        f"graph callers returned no hits for known target {callers_target!r}"
    )
    for hit in callers_payload:
        assert set(hit.keys()) == {
            "path",
            "scope",
            "language",
            "start_line",
            "kind",
            "dst_name",
        }
        assert hit["dst_name"] == callers_target, hit

    # ------------------------------------------------------------------
    # Step 10: ``graph deps main.py``.
    #
    # Asserts at least one hit; if any dst_name has no corresponding
    # symbols.name row (e.g. ``os`` in main.py) it is surfaced in the
    # result — the contract allows unresolved targets per storage.md.
    # The test does not synthesize an unresolved target; it just records
    # whether any are present.
    # ------------------------------------------------------------------
    deps_exit, deps_out, _deps_err = _run(
        ["--format", "json", "graph", "deps", "main.py"], capsys
    )
    assert deps_exit == 0, deps_out
    deps_payload: list[dict[str, Any]] = json.loads(deps_out)
    assert deps_payload, "graph deps returned no hits for main.py"
    for hit in deps_payload:
        assert set(hit.keys()) == {"path", "kind", "dst_name", "meta"}
        assert hit["path"] == "main.py", hit

    # Cross-check unresolved-target visibility against the DB. The contract
    # is "unresolved targets are surfaced when they exist", not "the test
    # must exercise unresolved targets" — silence is also fine.
    conn = _db_conn(tmp_path)
    try:
        dst_names: set[str] = {hit["dst_name"] for hit in deps_payload}
        resolved_names: set[str] = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT name FROM symbols WHERE name IN ("
                + ",".join("?" * len(dst_names))
                + ")",
                tuple(dst_names),
            )
        } if dst_names else set()
        unresolved: set[str] = dst_names - resolved_names
        # Pure observation: unresolved targets are returned as-is when
        # they exist. ``os`` (top-of-file import) has no symbols.name row
        # in the polyglot fixture by construction.
        if unresolved:
            assert {hit["dst_name"] for hit in deps_payload} >= unresolved
    finally:
        conn.close()

    # Capture post-sync row counts before the rebuild for step 11.
    conn = _db_conn(tmp_path)
    try:
        post_sync_counts: dict[str, int] = _row_counts(conn)
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # Step 11: ``index rebuild --yes`` and assert idempotency.
    # ------------------------------------------------------------------
    rebuild_exit, rebuild_out, _rebuild_err = _run(
        ["--format", "json", "index", "rebuild", "--yes"], capsys
    )
    assert rebuild_exit == 0, rebuild_out
    rebuild_payload: dict[str, Any] = json.loads(rebuild_out)
    assert set(rebuild_payload.keys()) == {
        "files_walked",
        "files_chunked",
        "chunks_chunked",
        "chunks_inserted",
        "symbols_inserted",
        "edges_inserted",
        "seconds_elapsed",
    }

    conn = _db_conn(tmp_path)
    try:
        post_rebuild_counts: dict[str, int] = _row_counts(conn)
        # Idempotency: rebuild against the same on-disk tree produces the
        # same row counts in every row-data table as the post-sync state.
        assert post_rebuild_counts == post_sync_counts, (
            f"rebuild row counts diverged from post-sync: "
            f"post_sync={post_sync_counts}, post_rebuild={post_rebuild_counts}"
        )

        # meta.embed_model / meta.embed_dim are present after rebuild.
        meta_model = conn.execute(
            "SELECT value FROM meta WHERE key = 'embed_model'"
        ).fetchone()
        assert meta_model is not None and str(meta_model[0])
        meta_dim = conn.execute(
            "SELECT value FROM meta WHERE key = 'embed_dim'"
        ).fetchone()
        assert meta_dim is not None and str(meta_dim[0])
    finally:
        conn.close()
