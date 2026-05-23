"""Tests for the ``code_index index build`` subcommand (step 004 of feature 004).

Four DoD cases per ``docs/plans/004.walker-and-build/004.index-build-cli.md``:

1. **DoD integration test** — copy the polyglot fixture to ``tmp_path``,
   run ``init`` then ``index build --root <tmp_path>``, and assert against
   the resulting ``docs/.helpers/index.sqlite``. This is the phase DoD.
2. **Auto-rebuild** — second invocation against the same tree exits 0 and
   row counts match the first run (not double).
3. **``--dry-run``** — fresh fixture; ``--dry-run`` exits 0 and writes no
   rows (the DB either does not exist or has zero rows in ``chunks`` /
   ``files``).
4. **No config found** — running from a tmp_path without a
   ``docs/.helpers/`` exits non-zero with an envelope pointing the user at
   ``code_index init``.

The integration tests exercise the real fastembed backend; the model is
loaded from the persistent ``tests/.cache/fastembed/`` cache populated by
Phase 2 (re-downloaded if absent — ~120 MB cold). To make the fastembed
backend reuse that cache when constructed from a config inside the CLI,
we monkeypatch :func:`code_index.indexer.from_config` to call
:class:`FastembedBackend` with the test cache_dir.

The polyglot fixture's ``.git/`` marker is created at test time per the
step context — checking in a real ``.git/`` is forbidden, so the test
creates an empty one inside ``tmp_path`` so the walker's ``.gitignore``
honoring path becomes active.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from code_index import indexer
from code_index.cli import _invoke, app
from code_index.embeddings.fastembed import FastembedBackend
from code_index.storage import open_index

FIXTURE_SRC: Path = (
    Path(__file__).parent / "fixtures" / "projects" / "polyglot_minimal"
)
_FASTEMBED_CACHE: str = "tests/.cache/fastembed"

#: Plugin names whose ``main.<ext>`` source lives in the fixture.
_EXPECTED_LANGUAGES: tuple[str, ...] = (
    "python",
    "csharp",
    "javascript",
    "typescript",
    "go",
    "fsharp",
    "lsl",
)

#: Relative paths (forward-slash) of the seven source files expected to be
#: indexed. The walker emits ``Path.as_posix()`` so the comparison is
#: byte-for-byte against these strings.
_EXPECTED_FILE_PATHS: tuple[str, ...] = (
    "main.cs",
    "main.fs",
    "main.go",
    "main.js",
    "main.lsl",
    "main.py",
    "main.ts",
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _copy_fixture(tmp_path: Path) -> None:
    """Copy ``polyglot_minimal/`` into ``tmp_path`` and add ``.git/``.

    ``shutil.copytree(..., dirs_exist_ok=True)`` handles the case where
    ``tmp_path`` already exists (pytest creates it). The ``.git/`` marker
    is created at test time per the step context; checking in a real
    ``.git/`` is forbidden by repo conventions.
    """
    shutil.copytree(FIXTURE_SRC, tmp_path, dirs_exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)


@pytest.fixture
def warm_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the indexer's backend factory to use the test cache.

    The factory at :func:`code_index.embeddings.factory.from_config` does
    not pass a ``cache_dir`` (that is by Phase 2 design). For the
    integration test we want fastembed to reuse ``tests/.cache/fastembed/``
    so CI does not redownload. Patch the symbol the indexer imports
    (``code_index.indexer.from_config``) — that is the binding the
    pipeline actually resolves at call time.
    """

    def _build_backend(config: Any) -> FastembedBackend:
        return FastembedBackend(
            model=config.embed_model,
            batch_size=config.embed_batch_size,
            cache_dir=_FASTEMBED_CACHE,
        )

    monkeypatch.setattr(indexer, "from_config", _build_backend)


def _db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Open the indexer's DB via the Phase 1 helper.

    The ``embeddings`` table is a ``vec0`` virtual table; counting rows in
    it requires the sqlite-vec extension to be loaded on the connection,
    which is what :func:`open_index` does.
    """
    return open_index(tmp_path / "docs" / ".helpers" / "index.sqlite")


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return current row counts for the six indexer-owned tables."""
    out: dict[str, int] = {}
    for table in ("chunks", "chunks_fts", "embeddings", "symbols", "edges", "files"):
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        out[table] = int(row[0]) if row is not None else 0
    return out


# ---------------------------------------------------------------------------
# DoD-1 — integration test (the phase DoD)
# ---------------------------------------------------------------------------


def test_dod_integration_polyglot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warm_fastembed: None,
) -> None:
    """``init`` then ``index build`` populates every indexer-owned table.

    Asserts: per-language chunks present; no rows for ``ignored/`` or
    ``data.bin``; ``meta.embed_model`` and ``meta.embed_dim`` set; FTS5
    row count equals chunks row count; symbols and edges non-empty; the
    ``files`` table has exactly the seven expected rows and every
    ``files.path`` matches a value in ``SELECT DISTINCT path FROM chunks``.
    """
    del warm_fastembed
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    build_result = runner.invoke(app, ["index", "build", "--root", str(tmp_path)])
    assert build_result.exit_code == 0, build_result.stderr
    # Text-mode summary lives on stdout.
    assert "indexed" in build_result.stdout
    assert "files" in build_result.stdout
    assert "chunks" in build_result.stdout

    conn = _db_conn(tmp_path)
    try:
        # Per-language chunk coverage: every plugin emitted at least one row.
        for language in _EXPECTED_LANGUAGES:
            row = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE language = ?",
                (language,),
            ).fetchone()
            assert row is not None and row[0] >= 1, (
                f"expected >=1 chunk for language {language!r}, got {row}"
            )

        # Ignored directory must not appear.
        row = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE path LIKE 'ignored/%'"
        ).fetchone()
        assert row is not None and row[0] == 0

        # Binary file must not appear.
        row = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE path LIKE '%data.bin'"
        ).fetchone()
        assert row is not None and row[0] == 0

        # meta keys set by the indexer.
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'embed_model'"
        ).fetchone()
        assert row is not None
        embed_model_value: str = str(row[0])
        # fastembed default short name, written by FastembedBackend.__init__.
        assert embed_model_value == "fastembed:jina-code-v2", embed_model_value

        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'embed_dim'"
        ).fetchone()
        assert row is not None and str(row[0]) == "768"

        # FTS5 row count tracks chunks row count.
        chunks_row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        fts_row = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()
        assert chunks_row is not None and fts_row is not None
        assert chunks_row[0] == fts_row[0]

        # symbols and edges populated (exact counts not asserted to avoid
        # coupling to per-plugin internals).
        for table in ("symbols", "edges"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert row is not None and row[0] > 0, (
                f"expected >0 rows in {table}, got {row}"
            )

        # files table: exactly seven rows, all matching `_EXPECTED_FILE_PATHS`.
        files_rows = list(
            conn.execute("SELECT path FROM files ORDER BY path")
        )
        files_paths: list[str] = [str(r[0]) for r in files_rows]
        assert files_paths == list(_EXPECTED_FILE_PATHS), files_paths

        # Every files.path matches a distinct chunks.path (byte-for-byte).
        chunk_paths: set[str] = {
            str(r[0])
            for r in conn.execute("SELECT DISTINCT path FROM chunks")
        }
        for fp in files_paths:
            assert fp in chunk_paths, (
                f"files.path {fp!r} has no matching chunks.path; "
                f"chunk_paths={sorted(chunk_paths)}"
            )

        # ignored/ and data.bin must also be absent from the files table.
        row = conn.execute(
            "SELECT COUNT(*) FROM files WHERE path LIKE 'ignored/%' OR path LIKE '%data.bin'"
        ).fetchone()
        assert row is not None and row[0] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DoD-2 — auto-rebuild on second invocation
# ---------------------------------------------------------------------------


def test_auto_rebuild_keeps_row_counts_equal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warm_fastembed: None,
) -> None:
    """Second ``index build`` against the same tree leaves row counts equal."""
    del warm_fastembed
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    first = runner.invoke(app, ["index", "build", "--root", str(tmp_path)])
    assert first.exit_code == 0, first.stderr

    conn = _db_conn(tmp_path)
    try:
        first_counts = _row_counts(conn)
    finally:
        conn.close()

    # Sanity: first run produced data in every relevant table.
    for table, count in first_counts.items():
        assert count > 0, (
            f"expected >0 rows in {table} after first build; counts={first_counts}"
        )
    assert first_counts["files"] == len(_EXPECTED_FILE_PATHS)

    second = runner.invoke(app, ["index", "build", "--root", str(tmp_path)])
    assert second.exit_code == 0, second.stderr

    conn = _db_conn(tmp_path)
    try:
        second_counts = _row_counts(conn)
    finally:
        conn.close()

    assert second_counts == first_counts, (
        f"auto-rebuild row counts diverged: first={first_counts}, "
        f"second={second_counts}"
    )


# ---------------------------------------------------------------------------
# DoD-3 — --dry-run writes no rows
# ---------------------------------------------------------------------------


def test_dry_run_writes_no_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warm_fastembed: None,
) -> None:
    """``index build --dry-run`` exits 0 and leaves chunks/files empty."""
    del warm_fastembed
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    result = runner.invoke(
        app, ["index", "build", "--root", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 0, result.stderr

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    if not db_path.exists():
        # Acceptable: dry-run did not open / create the DB at all.
        return

    conn = sqlite3.connect(str(db_path))
    try:
        for table in ("chunks", "files"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert row is not None and row[0] == 0, (
                f"dry-run wrote {row} rows to {table}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bug-fix regression — `chunks_chunked` JSON shape under build / dry-run.
# ---------------------------------------------------------------------------


def test_json_includes_chunks_chunked_under_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warm_fastembed: None,
) -> None:
    """``--dry-run`` JSON reports ``chunks_chunked > 0`` with ``chunks_inserted == 0``.

    Regression for the bug where dry-run's per-file verbose lines showed
    positive chunk counts but the aggregate JSON / text summary printed
    zero chunks (because only ``chunks_inserted`` was exposed). The fix
    adds ``chunks_chunked`` to :class:`IndexerResult` and to the CLI's
    JSON payload.
    """
    del warm_fastembed
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "index",
            "build",
            "--root",
            str(tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stderr

    payload: dict[str, Any] = json.loads(result.stdout)
    assert "chunks_chunked" in payload, payload
    assert "chunks_inserted" in payload, payload
    assert payload["chunks_chunked"] > 0, payload
    assert payload["chunks_inserted"] == 0, payload


def test_json_chunks_chunked_equals_inserted_in_real_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warm_fastembed: None,
) -> None:
    """In a real build ``chunks_chunked == chunks_inserted`` (no dry-run gate).

    Pinning this keeps text-mode output meaningful for both modes: the
    summary line reads ``chunks_chunked``, which equals what the user
    would have called "chunks indexed" outside dry-run.
    """
    del warm_fastembed
    _copy_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    result = runner.invoke(
        app,
        ["--format", "json", "index", "build", "--root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stderr

    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["chunks_chunked"] > 0, payload
    assert payload["chunks_inserted"] == payload["chunks_chunked"], payload


# ---------------------------------------------------------------------------
# DoD-4 — no config found
# ---------------------------------------------------------------------------


def test_no_config_found_errors_with_init_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ``index build`` outside a configured project exits non-zero.

    Uses :func:`code_index.cli._invoke` so the boundary handler routes the
    :class:`CodeIndexError` raised by config discovery into the standard
    envelope on stderr (text mode) / stdout (JSON mode). Asserts the
    envelope points the user at ``code_index init`` per Phase 1's
    discovery error.
    """
    monkeypatch.chdir(tmp_path)

    capsys.readouterr()
    exit_code: int = _invoke(["--format", "json", "index", "build"])
    captured = capsys.readouterr()

    assert exit_code != 0
    envelope: dict[str, Any] = json.loads(captured.out)
    assert "error" in envelope
    error: dict[str, Any] = envelope["error"]
    # The Phase 1 discovery surface for "no config found" maps to
    # `index.missing` (code 12) per cli.py's `_resolve_config_path`.
    assert error["kind"] == "index.missing"
    assert error["code"] == 12
    assert "code_index init" in error["message"]
