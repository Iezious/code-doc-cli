"""Phase 7 DoD: cross-subcommand JSON round-trip integration tests.

Covers ``docs/plans/007.config-show-json-polish/005.json-roundtrip-dod.md`` —
the Phase 7 Definition of Done as written in
``docs/architecture/mvp-phases.md``:

    every MVP subcommand under ``--format json`` round-trips through
    ``json.loads``; the same subcommands under failure conditions emit a
    parseable error envelope.

Every MVP subcommand from ``docs/architecture/cli.md`` is exercised twice:

* Success path -> ``json.loads(stdout)`` succeeds and the top-level shape
  matches the contract pinned by each subcommand's originating phase.
* Failure path -> ``json.loads(stdout)`` succeeds against an
  ``{"error": {...}}`` envelope, ``error.code == result.exit_code``, and
  ``error.kind`` matches the documented kind for that failure mode.

Tests drive the CLI through :func:`code_index.cli._invoke` so the Phase 1
boundary handler routes :class:`CodeIndexError` envelopes to stdout (same
pattern as ``tests/test_config_show.py``, ``tests/test_index_build_cli.py``,
``tests/test_phase6_dod.py``). The ``CliRunner`` route the step file
suggests is bypassed for the same reason ``tests/test_init_json.py``
bypasses it for the refuse-path case — ``CliRunner`` does not re-enter
the :class:`BoundaryTyper.__call__` wrapper that emits envelopes to stdout.

Performance: a real ``index build`` against the polyglot fixture
downloads the fastembed model on first invocation. A session-scoped
``built_project`` fixture runs init + build once and yields the path so
read-only success-path tests can re-use it (per ``005.context.md``
"Session-fixture strategy"). The fastembed cache lives at
``tests/.cache/fastembed/`` and is shared with the other phase DoD
tests.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from code_index import embeddings, indexer
from code_index.cli import _invoke
from code_index.embeddings.fastembed import FastembedBackend
from code_index.errors import Kinds

FIXTURE_SRC: Path = (
    Path(__file__).parent / "fixtures" / "projects" / "polyglot_minimal"
)
# Absolute path so a later ``monkeypatch.chdir`` does not resolve it under
# ``tmp_path`` and miss the shared cache. Mirrors test_phase6_dod.py.
_FASTEMBED_CACHE: str = str(
    (Path(__file__).resolve().parent / ".cache" / "fastembed").resolve()
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke through the boundary handler; return ``(exit_code, out, err)``."""
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _build_cache_aware_backend(config: Any) -> FastembedBackend:
    """Return a fastembed backend pointed at the persistent test cache."""
    return FastembedBackend(
        model=config.embed_model,
        batch_size=config.embed_batch_size,
        cache_dir=_FASTEMBED_CACHE,
    )


def _patch_backend_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every binding of :func:`embeddings.from_config` used by the CLI.

    The indexer module captures :func:`from_config` at import time (Phase 4
    deliberately preserved that binding), and the search / sync / symbols /
    graph paths resolve it through :mod:`code_index.embeddings`. Patch both
    so every code path picks the cache-aware backend.
    """
    monkeypatch.setattr(embeddings, "from_config", _build_cache_aware_backend)
    monkeypatch.setattr(indexer, "from_config", _build_cache_aware_backend)


def _copy_fixture(dst: Path) -> None:
    """Copy ``polyglot_minimal/`` into ``dst`` and add ``.git/`` marker."""
    shutil.copytree(FIXTURE_SRC, dst, dirs_exist_ok=True)
    (dst / ".git").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Session fixture: build the polyglot index once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def built_project(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Copy the polyglot fixture, run ``init`` + ``index build`` once.

    Session-scoped per ``005.context.md`` "Why session-scope for
    ``built_project``" — running ``index build`` is ~5-15 seconds on a warm
    cache and significantly slower on a cold one. Tests that need to mutate
    the index copy this tree into a function-scoped ``tmp_path`` first.

    The fastembed backend is patched at session scope via a temporary
    :class:`MonkeyPatch` so the cache directory is honored even though the
    rest of the suite is function-scoped.
    """
    dst: Path = tmp_path_factory.mktemp("polyglot_built")
    _copy_fixture(dst)

    monkeypatch = pytest.MonkeyPatch()
    try:
        _patch_backend_factory(monkeypatch)
        monkeypatch.chdir(dst)

        exit_code: int = _invoke(["init"])
        assert exit_code == 0, "session built_project init failed"

        exit_code = _invoke(["index", "build", "--root", str(dst)])
        assert exit_code == 0, "session built_project index build failed"
    finally:
        monkeypatch.undo()

    return dst


@pytest.fixture
def read_only_built(
    built_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Chdir into the session-built tree and patch the backend factory.

    Use for read-only subcommands (``search``, ``symbols``, ``graph``,
    ``config show``) that do not mutate the index — the session tree stays
    intact across tests.
    """
    _patch_backend_factory(monkeypatch)
    monkeypatch.chdir(built_project)
    return built_project


@pytest.fixture
def mutable_built(
    built_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Copy the session-built tree into ``tmp_path`` for tests that mutate.

    Required for ``index sync``, ``index rebuild``, schema-mismatch carve-out,
    and ``index sync`` model-mismatch failure path — anything that writes to
    the index or to the on-disk source. Patches the backend factory the same
    way ``read_only_built`` does so any incidental backend construction (e.g.
    ``_preflight``'s mandatory backend) reuses the cache.
    """
    shutil.copytree(built_project, tmp_path, dirs_exist_ok=True)
    _patch_backend_factory(monkeypatch)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------


def _assert_error_envelope(
    parsed: dict[str, Any], exit_code: int, expected_kind: str | None
) -> None:
    """Assert ``parsed`` is the ``{"error": {...}}`` envelope shape.

    ``parsed["error"]["code"]`` must equal ``exit_code``; ``parsed["error"]
    ["message"]`` must be a non-empty string (no regex match on contents
    per ``errors-and-exit-codes.md`` "Implications"). When ``expected_kind``
    is given, ``parsed["error"]["kind"]`` must match exactly.
    """
    assert "error" in parsed, parsed
    error: dict[str, Any] = parsed["error"]
    assert set(error.keys()) >= {"code", "kind", "message"}, error
    assert isinstance(error["code"], int)
    assert error["code"] == exit_code, (error["code"], exit_code)
    assert isinstance(error["kind"], str) and error["kind"], error
    assert isinstance(error["message"], str) and error["message"], error
    if expected_kind is not None:
        assert error["kind"] == expected_kind, error


def _set_meta_direct(db_path: Path, key: str, value: str) -> None:
    """Mutate ``meta`` directly via :mod:`sqlite3` (no engine schema check)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# init
# ===========================================================================


def test_init_success_json_roundtrips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``init --format json`` against an empty dir round-trips to a four-key dict."""
    monkeypatch.chdir(tmp_path)

    exit_code, out, _err = _run(["--format", "json", "init"], capsys)
    assert exit_code == 0, out

    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "config_path",
        "gitignore_path",
        "project",
        "force_used",
    }


def test_init_refuse_without_force_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Second ``init`` (no ``--force``) emits a parseable error envelope.

    Per the step-file table, ``init``'s refuse-path kind is "whatever Phase
    4 pinned"; the DoD assertion is structural only (envelope round-trips,
    ``error.code == exit_code``, ``error.message`` non-empty).
    """
    monkeypatch.chdir(tmp_path)
    first_exit, _first_out, _first_err = _run(["init"], capsys)
    assert first_exit == 0

    exit_code, out, _err = _run(["--format", "json", "init"], capsys)
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=None)


# ===========================================================================
# index build
# ===========================================================================


def test_index_build_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index build`` JSON shape matches Phase 4's six-key contract.

    The session-scoped ``built_project`` already ran ``index build`` once;
    re-running it here is idempotent against an up-to-date tree. The DoD
    assertion is shape-only.
    """
    del read_only_built  # consumed via monkeypatch side effects
    exit_code, out, _err = _run(
        ["--format", "json", "index", "build"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "files_walked",
        "files_chunked",
        "chunks_inserted",
        "symbols_inserted",
        "edges_inserted",
        "seconds_elapsed",
    }


def test_index_build_missing_config_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index build`` without a discovered config -> ``index.missing``."""
    monkeypatch.chdir(tmp_path)
    exit_code, out, _err = _run(
        ["--format", "json", "index", "build"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


# ===========================================================================
# index sync
# ===========================================================================


def test_index_sync_success_json_roundtrips(
    mutable_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index sync`` against an unmodified tree round-trips to the six-key shape."""
    del mutable_built
    exit_code, out, _err = _run(
        ["--format", "json", "index", "sync"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "files_added",
        "files_changed",
        "files_unchanged",
        "files_removed",
        "chunks_inserted_total",
        "seconds_elapsed",
    }


def test_index_sync_model_mismatch_emits_envelope(
    mutable_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Corrupting ``meta.embed_model`` yields ``index.embed_model_mismatch``."""
    db_path: Path = mutable_built / "docs" / ".helpers" / "index.sqlite"
    _set_meta_direct(db_path, "embed_model", "wrong:model")

    exit_code, out, _err = _run(
        ["--format", "json", "index", "sync"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(
        parsed, exit_code, expected_kind=Kinds.INDEX_EMBED_MODEL_MISMATCH
    )


# ===========================================================================
# index rebuild
# ===========================================================================


def test_index_rebuild_success_json_roundtrips(
    mutable_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index rebuild --yes`` matches ``index build``'s six-key contract."""
    del mutable_built
    exit_code, out, _err = _run(
        ["--format", "json", "index", "rebuild", "--yes"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "files_walked",
        "files_chunked",
        "chunks_inserted",
        "symbols_inserted",
        "edges_inserted",
        "seconds_elapsed",
    }


def test_index_rebuild_missing_yes_emits_envelope(
    mutable_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index rebuild`` without ``--yes`` -> ``usage.confirmation_required``."""
    del mutable_built
    exit_code, out, _err = _run(
        ["--format", "json", "index", "rebuild"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(
        parsed, exit_code, expected_kind=Kinds.USAGE_CONFIRMATION_REQUIRED
    )


# ===========================================================================
# search
# ===========================================================================


def test_search_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``search foo --mode hybrid`` returns ``{"results": [...]}``."""
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "search", "foo", "--mode", "hybrid"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert "results" in parsed
    assert isinstance(parsed["results"], list)


def test_search_zero_results_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A query that matches nothing still returns ``{"results": []}`` (exit 0).

    "Zero-results is not an error" — guards against the case where a
    subcommand emits nothing on empty results and breaks ``json.loads``.
    Uses ``--mode bm25`` to force a text-only match: dense / hybrid always
    return some top-k from the embedding space even for nonsense queries
    (per Phase 5's retrieval contract — dense scores everything), so the
    only way to test the genuine empty path is the BM25 channel.
    """
    del read_only_built
    exit_code, out, _err = _run(
        [
            "--format",
            "json",
            "search",
            "xyz_definitely_no_match_token_zzz",
            "--mode",
            "bm25",
        ],
        capsys,
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert parsed == {"results": []}


def test_search_bad_mode_emits_envelope(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--mode garbage`` -> ``cli.bad_enum`` (Phase 7 step 004)."""
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "search", "foo", "--mode", "garbage"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.CLI_BAD_ENUM)


# ===========================================================================
# symbols defs / refs
# ===========================================================================


def _pick_symbols_name(db_path: Path, kind: str) -> str | None:
    """Pull a symbol ``name`` of the given ``kind`` from the index."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM symbols WHERE kind = ? LIMIT 1", (kind,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row[0])


def test_symbols_defs_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols defs <known-name>`` round-trips to a list of five-key dicts.

    The known name is read directly from the index — the polyglot fixture
    is plugin-owned and the test should not hardcode names.
    """
    db_path: Path = read_only_built / "docs" / ".helpers" / "index.sqlite"
    known_name: str | None = _pick_symbols_name(db_path, "def")
    assert known_name is not None, "polyglot fixture produced zero def symbols"

    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "defs", known_name], capsys
    )
    assert exit_code == 0, out
    parsed: Any = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed, parsed
    for hit in parsed:
        assert set(hit.keys()) == {"path", "scope", "language", "name", "line"}


def test_symbols_defs_zero_results_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols defs zzz_nope`` returns ``[]`` with exit 0 (not silent)."""
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "defs", "zzz_definitely_no_match"],
        capsys,
    )
    assert exit_code == 0, out
    assert json.loads(out) == []


def test_symbols_defs_missing_index_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols defs`` without an index -> ``index.missing``."""
    monkeypatch.chdir(tmp_path)
    # Run init so the config exists; the index file is absent.
    init_exit, _init_out, _init_err = _run(["init"], capsys)
    assert init_exit == 0

    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "defs", "anything"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


def test_symbols_refs_zero_results_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols refs`` empty-result case round-trips.

    The polyglot fixture may produce zero ``ref`` symbols depending on plugin
    coverage; use a sentinel name that is guaranteed to miss either way.
    """
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "refs", "zzz_definitely_no_match"],
        capsys,
    )
    assert exit_code == 0, out
    assert json.loads(out) == []


def test_symbols_refs_success_shape(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols refs <ref-name-if-any>`` either has hits with the five-key shape
    or is empty — both round-trip.

    Reads a candidate ``ref`` from the DB; if no ``ref`` rows exist, falls
    back to a sentinel query and asserts the empty-list contract.
    """
    db_path: Path = read_only_built / "docs" / ".helpers" / "index.sqlite"
    candidate: str | None = _pick_symbols_name(db_path, "ref")
    target: str = candidate if candidate is not None else "zzz_no_match"

    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "refs", target], capsys
    )
    assert exit_code == 0, out
    parsed: Any = json.loads(out)
    assert isinstance(parsed, list)
    for hit in parsed:
        assert set(hit.keys()) == {"path", "scope", "language", "name", "line"}


def test_symbols_refs_missing_index_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols refs`` without an index -> ``index.missing``."""
    monkeypatch.chdir(tmp_path)
    init_exit, _init_out, _init_err = _run(["init"], capsys)
    assert init_exit == 0

    exit_code, out, _err = _run(
        ["--format", "json", "symbols", "refs", "anything"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


# ===========================================================================
# graph callers / deps
# ===========================================================================


def _pick_edge_dst(db_path: Path) -> str | None:
    """Pull an ``edges.dst_name`` value from the index."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT dst_name FROM edges LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row[0])


def test_graph_callers_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph callers <known-name>`` returns a list of six-key dicts."""
    db_path: Path = read_only_built / "docs" / ".helpers" / "index.sqlite"
    target: str | None = _pick_edge_dst(db_path)
    assert target is not None, "polyglot fixture produced zero edges"

    exit_code, out, _err = _run(
        ["--format", "json", "graph", "callers", "--exact", target], capsys
    )
    assert exit_code == 0, out
    parsed: Any = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed, parsed
    for hit in parsed:
        assert set(hit.keys()) == {
            "path",
            "scope",
            "language",
            "start_line",
            "kind",
            "dst_name",
        }


def test_graph_callers_zero_results_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph callers <missing-target>`` returns ``[]`` with exit 0."""
    del read_only_built
    exit_code, out, _err = _run(
        [
            "--format",
            "json",
            "graph",
            "callers",
            "--exact",
            "zzz_definitely_no_match",
        ],
        capsys,
    )
    assert exit_code == 0, out
    assert json.loads(out) == []


def test_graph_callers_missing_index_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph callers`` without an index -> ``index.missing``."""
    monkeypatch.chdir(tmp_path)
    init_exit, _init_out, _init_err = _run(["init"], capsys)
    assert init_exit == 0

    exit_code, out, _err = _run(
        ["--format", "json", "graph", "callers", "anything"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


def test_graph_deps_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph deps main.py`` round-trips to a list of four-key dicts.

    ``meta`` is intentionally a raw JSON string or ``None`` per decision 7;
    the assertion is structural (either string or ``None``), not on its
    decoded contents.
    """
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "graph", "deps", "main.py"], capsys
    )
    assert exit_code == 0, out
    parsed: Any = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed, parsed
    for hit in parsed:
        assert set(hit.keys()) == {"path", "kind", "dst_name", "meta"}
        assert hit["meta"] is None or isinstance(hit["meta"], str), hit


def test_graph_deps_zero_results_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph deps`` against a non-matching path returns ``[]`` with exit 0."""
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "graph", "deps", "zzz_no_such_path.py"], capsys
    )
    assert exit_code == 0, out
    assert json.loads(out) == []


def test_graph_deps_missing_index_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph deps`` without an index -> ``index.missing``."""
    monkeypatch.chdir(tmp_path)
    init_exit, _init_out, _init_err = _run(["init"], capsys)
    assert init_exit == 0

    exit_code, out, _err = _run(
        ["--format", "json", "graph", "deps", "main.py"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


# ===========================================================================
# config show
# ===========================================================================


def test_config_show_success_json_roundtrips(
    read_only_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``config show`` returns ``{"config": {...}, "index": {...}}``."""
    del read_only_built
    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {"config", "index"}
    assert isinstance(parsed["config"], dict)
    assert parsed["index"] is None or isinstance(parsed["index"], dict)


def test_config_show_missing_config_emits_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``config show`` without a discovered config -> ``index.missing``.

    Per the Phase 7 carve-out the failure-path test for ``config show`` is
    "no config discovered"; schema mismatch is a success-path emission
    (covered by :func:`test_config_show_schema_mismatch_does_not_gate`).
    """
    monkeypatch.chdir(tmp_path)

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code != 0
    parsed: dict[str, Any] = json.loads(out)
    _assert_error_envelope(parsed, exit_code, expected_kind=Kinds.INDEX_MISSING)


def test_config_show_schema_mismatch_does_not_gate(
    mutable_built: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Schema-mismatch carve-out: ``config show`` reports drift; exit 0.

    The DoD assertion is re-asserted here at the cross-subcommand level:
    after build, force ``meta.schema_version = "99"``; ``config show
    --format json`` must exit 0 and emit ``index.schema_version == "99"``.
    """
    db_path: Path = mutable_built / "docs" / ".helpers" / "index.sqlite"
    _set_meta_direct(db_path, "schema_version", "99")

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    assert isinstance(parsed["index"], dict)
    assert parsed["index"]["schema_version"] == "99"
    assert "error" not in parsed
