"""End-to-end tests for the ``code_index search`` subcommand (Phase 5 DoD).

Builds the Phase 4 polyglot fixture once per pytest session via
``code_index init`` + ``code_index index build``, then exercises every
DoD bullet from ``docs/plans/005.search/002.search-cli.md`` against the
resulting index.

The fixture under ``tests/fixtures/projects/polyglot_minimal/`` is
augmented (Option A from ``002.context.md``): ``main.py`` carries a
``def search_me() -> None`` with the docstring "Handle dropped websocket
sessions with a reconnection loop." That single function provides both
the known-symbol-name target (``search_me``) and the known-conceptual
target ("websocket reconnection on drop"). The augmentation is small
and additive — Phase 4's per-language coverage assertions stay green
because they only require ``>=1`` chunk per language.

The fastembed model cache from Phase 2's ``tests/.cache/fastembed/`` is
reused by patching the package-level :func:`code_index.embeddings.from_config`
(and :func:`code_index.indexer.from_config` for the one-time index
build) to construct :class:`FastembedBackend` with the test cache_dir.
This mirrors the pattern in ``tests/test_index_build_cli.py``; without
it the CLI's own factory call would attempt a fresh ~120 MB download.

Tests that assert the success path use ``typer.testing.CliRunner``
because CliRunner captures ``sys.stdout`` cleanly. Tests that assert
the JSON error envelope drive the CLI through
:func:`code_index.cli._invoke` plus ``capsys`` — :class:`CliRunner` does
not route exceptions through the Phase 1 boundary handler, so an error
envelope would never reach stdout via CliRunner.

Function-scoped tests that mutate the index (e.g. the model-drift test)
copy the session-built tree to a function-scoped ``tmp_path`` first so
the session-level data stays clean.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from code_index import embeddings, indexer
from code_index.cli import _invoke, app
from code_index.embeddings.fastembed import FastembedBackend

FIXTURE_SRC: Path = (
    Path(__file__).parent / "fixtures" / "projects" / "polyglot_minimal"
)
_FASTEMBED_CACHE: str = "tests/.cache/fastembed"


def _cache_backend(config: Any) -> FastembedBackend:
    """Replacement factory that points fastembed at the persistent test cache."""
    return FastembedBackend(
        model=config.embed_model,
        batch_size=config.embed_batch_size,
        cache_dir=_FASTEMBED_CACHE,
    )


# ---------------------------------------------------------------------------
# Session fixture: build the polyglot index once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def polyglot_index(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy the polyglot fixture to a session tmpdir and run init + build.

    The same patched ``from_config`` factory is installed for the build
    step so the indexer reuses the test fastembed cache. Returns the
    project directory so per-test functions can ``monkeypatch.chdir``
    into it.

    Implementation note: we cannot use the function-scoped ``monkeypatch``
    here because the fixture is session-scoped. We use
    :class:`pytest.MonkeyPatch` directly and undo at the end.
    """
    project_dir: Path = tmp_path_factory.mktemp("polyglot_session")
    shutil.copytree(FIXTURE_SRC, project_dir, dirs_exist_ok=True)
    (project_dir / ".git").mkdir(exist_ok=True)

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(indexer, "from_config", _cache_backend)
        mp.setattr(embeddings, "from_config", _cache_backend)
        mp.chdir(project_dir)

        runner: CliRunner = CliRunner()
        init_result = runner.invoke(app, ["init"])
        assert init_result.exit_code == 0, init_result.stderr

        build_result = runner.invoke(
            app, ["index", "build", "--root", str(project_dir)]
        )
        assert build_result.exit_code == 0, build_result.stderr
    finally:
        mp.undo()

    return project_dir


@pytest.fixture
def use_cached_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test patch so the CLI search path reuses the test fastembed cache.

    The CLI calls :func:`code_index.embeddings.from_config` at runtime;
    swapping the module-level attribute is enough because the CLI dereferences
    it on each invocation.
    """
    monkeypatch.setattr(embeddings, "from_config", _cache_backend)


@pytest.fixture
def chdir_polyglot(
    polyglot_index: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """``monkeypatch.chdir`` into the session-built polyglot project."""
    monkeypatch.chdir(polyglot_index)
    return polyglot_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_results(stdout: str) -> list[dict[str, Any]]:
    """Parse a search JSON document and return the ``results`` list."""
    parsed: dict[str, Any] = json.loads(stdout)
    assert "results" in parsed, f"missing results key in {parsed!r}"
    rows: list[dict[str, Any]] = parsed["results"]
    return rows


def _run_via_boundary(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke the CLI through the Phase 1 boundary handler.

    Returns ``(exit_code, stdout, stderr)``. The boundary handler routes
    :class:`CodeIndexError` instances through the stream helpers, so this
    is the only path that produces the JSON error envelope on stdout.
    """
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------------------
# DoD: known symbol-name query.
# ---------------------------------------------------------------------------


def test_symbol_name_query_returns_expected_path(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    """``search "search_me"`` finds the augmented Python function chunk."""
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "search", "search_me"])
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one result for symbol-name query"
    top = rows[0]
    assert top["path"] == "main.py"
    assert top["language"] == "python"
    assert top["name"] == "search_me"
    # The function spans lines 10..12 in the augmented fixture
    # (def line, docstring, pass).
    assert top["start_line"] >= 10
    assert top["end_line"] >= top["start_line"]


# ---------------------------------------------------------------------------
# DoD: known conceptual query.
# ---------------------------------------------------------------------------


def test_conceptual_query_finds_docstring_chunk(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    """A natural-language query locks onto the websocket-reconnection chunk."""
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        ["--format", "json", "search", "websocket reconnection on drop"],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one result for conceptual query"
    top = rows[0]
    assert top["path"] == "main.py"
    assert top["name"] == "search_me"


# ---------------------------------------------------------------------------
# DoD: --mode bm25 does not instantiate the embedding backend.
# ---------------------------------------------------------------------------


def test_mode_bm25_skips_backend_instantiation(
    chdir_polyglot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--mode bm25`` must not call :func:`embeddings.from_config`.

    Replaces the factory with one that raises; the test still passes,
    proving the bm25 code path skips backend instantiation entirely.
    """
    del chdir_polyglot

    def _explode(_config: Any) -> FastembedBackend:
        raise AssertionError(
            "embeddings.from_config must not be called in --mode bm25"
        )

    monkeypatch.setattr(embeddings, "from_config", _explode)

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        ["--format", "json", "search", "search_me", "--mode", "bm25"],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one BM25 hit for 'search_me'"
    assert rows[0]["name"] == "search_me"


# ---------------------------------------------------------------------------
# DoD: --mode dense runs and returns rows.
# ---------------------------------------------------------------------------


def test_mode_dense_returns_results(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "search",
            "websocket reconnection on drop",
            "--mode",
            "dense",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one dense hit"


# ---------------------------------------------------------------------------
# DoD: --mode hybrid matches default.
# ---------------------------------------------------------------------------


def test_mode_hybrid_matches_default(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    """``--mode hybrid`` returns the same list as no ``--mode`` flag."""
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    explicit = runner.invoke(
        app,
        ["--format", "json", "search", "search_me", "--mode", "hybrid"],
    )
    default = runner.invoke(
        app, ["--format", "json", "search", "search_me"]
    )
    assert explicit.exit_code == 0, explicit.stderr or explicit.stdout
    assert default.exit_code == 0, default.stderr or default.stdout

    explicit_rows = _json_results(explicit.stdout)
    default_rows = _json_results(default.stdout)
    assert len(explicit_rows) == len(default_rows)
    # Compare by (path, start_line, end_line) — a stable proxy for chunk id.
    explicit_key = [
        (r["path"], r["start_line"], r["end_line"]) for r in explicit_rows
    ]
    default_key = [
        (r["path"], r["start_line"], r["end_line"]) for r in default_rows
    ]
    assert explicit_key == default_key


# ---------------------------------------------------------------------------
# DoD: --format json shape — every row has all nine SearchResult fields.
# ---------------------------------------------------------------------------


def test_json_shape_contains_all_search_result_fields(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app, ["--format", "json", "search", "search_me"]
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows
    expected_keys: set[str] = {
        "path",
        "start_line",
        "end_line",
        "language",
        "kind",
        "name",
        "scope",
        "excerpt",
        "score",
    }
    for row in rows:
        assert set(row.keys()) == expected_keys, row


# ---------------------------------------------------------------------------
# DoD: zero results — text mode.
# ---------------------------------------------------------------------------


def test_zero_results_text_mode_empty_stdout(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    """Truly-empty result list under text mode writes nothing on stdout.

    Uses ``--mode bm25`` so the dense pool's nearest-neighbor floor cannot
    surface unrelated chunks — BM25 FTS5 returns zero rows for a token
    that does not exist in the corpus, satisfying the literal "no results"
    contract.
    """
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "search",
            "definitely_not_in_the_fixture_xyzzy",
            "--mode",
            "bm25",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    assert result.stdout == "", repr(result.stdout)


# ---------------------------------------------------------------------------
# DoD: zero results — JSON mode.
# ---------------------------------------------------------------------------


def test_zero_results_json_mode_empty_list(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "search",
            "definitely_not_in_the_fixture_xyzzy",
            "--mode",
            "bm25",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    parsed = json.loads(result.stdout)
    assert parsed == {"results": []}


# ---------------------------------------------------------------------------
# DoD: --lang python filter restricts results.
# ---------------------------------------------------------------------------


def test_lang_python_filter_returns_only_python(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "search",
            "greet",
            "--lang",
            "python",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one python hit for 'greet'"
    for row in rows:
        assert row["language"] == "python", row


# ---------------------------------------------------------------------------
# DoD: --lang invalid rejection — driven through the boundary handler so
# the JSON envelope reaches stdout.
# ---------------------------------------------------------------------------


def test_lang_invalid_rejection_emits_envelope(
    chdir_polyglot: Path,
    use_cached_backend: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del use_cached_backend
    del chdir_polyglot

    code, out, _err = _run_via_boundary(
        ["--format", "json", "search", "x", "--lang", "fortran"], capsys
    )
    assert code == 2, out
    envelope = json.loads(out)
    assert envelope["error"]["kind"] == "config.unknown_language"
    assert envelope["error"]["code"] == 2


# ---------------------------------------------------------------------------
# DoD: --kind function filter restricts results.
# ---------------------------------------------------------------------------


def test_kind_function_filter(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "search",
            "greet",
            "--kind",
            "function",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one function hit for 'greet'"
    for row in rows:
        assert row["kind"] == "function", row


# ---------------------------------------------------------------------------
# DoD: --path glob filter restricts results.
# ---------------------------------------------------------------------------


def test_path_glob_filter(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "search",
            "greet",
            "--path",
            "*main.py",
        ],
    )
    assert result.exit_code == 0, result.stderr or result.stdout
    rows = _json_results(result.stdout)
    assert rows, "expected at least one main.py hit for 'greet'"
    for row in rows:
        # SQLite GLOB ``*main.py`` matches both ``main.py`` and ``sub/main.py``.
        assert row["path"].endswith("main.py"), row


# ---------------------------------------------------------------------------
# DoD: no index found — driven through the boundary handler.
# ---------------------------------------------------------------------------


def test_no_index_found_exits_index_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running from a tree with config but no ``index.sqlite`` exits 12."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0, init_result.stderr

    code, out, _err = _run_via_boundary(
        ["--format", "json", "search", "x", "--mode", "bm25"], capsys
    )
    assert code == 12, out
    envelope = json.loads(out)
    assert envelope["error"]["kind"] == "index.missing"
    assert envelope["error"]["code"] == 12
    msg: str = envelope["error"]["message"]
    assert "code_index init" in msg or "index build" in msg


# ---------------------------------------------------------------------------
# DoD: wrong embed_model drift error.
# ---------------------------------------------------------------------------


def test_embed_model_mismatch_drift_error(
    polyglot_index: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_cached_backend: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tamper with ``meta.embed_model`` and expect a code-11 drift error.

    Copies the session-built project into ``tmp_path`` so the session
    index stays clean. Overwrites ``meta.embed_model`` via raw SQL, then
    runs ``search --mode hybrid`` and asserts the drift envelope on
    stdout via the boundary handler.
    """
    del use_cached_backend

    project_copy: Path = tmp_path / "project"
    shutil.copytree(polyglot_index, project_copy)
    monkeypatch.chdir(project_copy)

    db_path: Path = project_copy / "docs" / ".helpers" / "index.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'embed_model'",
            ("voyage:code-3",),
        )
        conn.commit()
    finally:
        conn.close()

    code, out, _err = _run_via_boundary(
        ["--format", "json", "search", "x", "--mode", "hybrid"], capsys
    )
    assert code == 11, out
    envelope = json.loads(out)
    assert envelope["error"]["kind"] == "index.embed_model_mismatch"
    assert envelope["error"]["code"] == 11
    assert "code_index index rebuild" in envelope["error"]["message"]


# ---------------------------------------------------------------------------
# --bm25-k 0 rejection (Typer's min=1 — exit code 2).
# ---------------------------------------------------------------------------


def test_bm25_k_zero_rejected_at_parse_time(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app, ["search", "search_me", "--bm25-k", "0"]
    )
    # Typer's min=1 rejects at parse time. Click's default usage-error exit
    # code is 2 — acceptable per 002.context.md.
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Bad --mode value: explicit pre-check raises cli.bad_enum (Phase 7 step 004).
# ---------------------------------------------------------------------------


def test_bad_mode_rejected_with_usage_error(
    chdir_polyglot: Path,
    use_cached_backend: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--mode <bad>`` -> exit 1, ``kind == "cli.bad_enum"``.

    Phase 7 step 004 replaced Typer's enum-driven exit-2 rejection with an
    explicit pre-check in ``cli_search`` that maps to
    :attr:`Kinds.CLI_BAD_ENUM` (code 1) so the envelope round-trips under
    ``--format json``. Routed through :func:`_invoke` because
    :class:`CliRunner` bypasses the boundary handler that emits the JSON
    envelope.
    """
    del use_cached_backend
    del chdir_polyglot

    exit_code, stdout, _stderr = _run_via_boundary(
        ["--format", "json", "search", "search_me", "--mode", "telepathic"],
        capsys,
    )
    assert exit_code == 1
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["code"] == 1
    assert error["kind"] == "cli.bad_enum"
    assert "telepathic" in error["message"]
    detail: dict[str, Any] = error["detail"]
    assert detail["flag"] == "--mode"
    assert detail["value"] == "telepathic"
    assert "hybrid" in detail["expected"]


# ---------------------------------------------------------------------------
# Text-mode stanza shape — sanity check.
# ---------------------------------------------------------------------------


def test_text_mode_stanza_shape(
    chdir_polyglot: Path,
    use_cached_backend: None,
) -> None:
    del use_cached_backend
    del chdir_polyglot

    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["search", "search_me"])
    assert result.exit_code == 0, result.stderr or result.stdout
    # First stanza's header must carry the file path, language tag, kind, name.
    first_line = result.stdout.splitlines()[0]
    assert "main.py:" in first_line
    assert "[python]" in first_line
    assert "function" in first_line
    assert "search_me" in first_line
