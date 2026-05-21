"""Tests for the ``code_index index rebuild`` CLI wrapper.

Covers the five scenarios pinned in
``docs/plans/006.sync-symbols-graph/002.rebuild-cli.md`` "Tests":

1. Happy path — row counts match the original ``index build``.
2. Missing ``--yes`` -> exit 1, ``kind == "usage.confirmation_required"``.
3. JSON summary shape matches the ``index build`` document.
4. No pre-flight model check — a mismatched ``meta.embed_model`` does NOT
   block the rebuild (rebuild is the cure for model mismatch per
   ``context.md`` decision 7); the post-rebuild meta reflects the
   configured backend.
5. No index yet — rebuild from an empty project degenerates to build.

Tests drive the CLI through :func:`code_index.cli._invoke` so the Phase 1
boundary handler routes :class:`CodeIndexError` envelopes to stdout
(matches the pattern in ``tests/test_sync_cli.py`` /
``tests/test_index_build_cli.py``). The fake plugin / backend doubles
mirror the doubles used by the sync-CLI tests to avoid loading fastembed
during the rebuild unit suite — the fastembed-on-polyglot DoD is owned
by step 005.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from code_index import embeddings, indexer, walker
from code_index.cli import _invoke
from code_index.config import CodeIndexConfig
from code_index.init import write_skeleton
from code_index.languages import Chunk, Edge, Symbol
from code_index.languages.registry import LanguageRegistry
from code_index.storage import get_meta, open_index, set_meta

_EMBED_DIM: int = 768


# ---------------------------------------------------------------------------
# Fake plugin / backend doubles (kept local; mirror tests/test_sync_cli.py)
# ---------------------------------------------------------------------------


@dataclass
class FakePlugin:
    name: str
    extensions: tuple[str, ...]
    chunks_by_path: dict[str, list[Chunk]]
    symbols_by_path: dict[str, list[Symbol]]
    edges_by_path: dict[str, list[Edge]]

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        del content
        return list(self.chunks_by_path.get(path.name, []))

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        del content
        return list(self.symbols_by_path.get(path.name, []))

    def imports(self, path: Path, content: str) -> list[Edge]:
        del content
        return list(self.edges_by_path.get(path.name, []))


class FakeBackend:
    name: str = "fake:tiny"
    dim: int = _EMBED_DIM

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        return np.zeros((len(texts), self.dim), dtype=np.float32)


def _make_plugin() -> FakePlugin:
    return FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path={
            "a.py": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="function",
                    name="alpha",
                    scope=None,
                    text="alpha",
                )
            ],
            "b.py": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="function",
                    name="beta",
                    scope=None,
                    text="beta",
                )
            ],
        },
        symbols_by_path={
            "a.py": [Symbol(name="alpha", kind="def", line=1)],
            "b.py": [Symbol(name="beta", kind="def", line=1)],
        },
        edges_by_path={
            "a.py": [Edge(target="dep", kind="import", line=1, meta=None)],
            "b.py": [Edge(target="dep", kind="import", line=1, meta=None)],
        },
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    plugin: FakePlugin,
    backend: FakeBackend,
) -> None:
    registry = LanguageRegistry([plugin])  # type: ignore[arg-type]
    monkeypatch.setattr(indexer, "active_plugins", lambda config: registry)
    monkeypatch.setattr(indexer, "from_config", lambda config: backend)
    monkeypatch.setattr(walker, "active_plugins", lambda config: registry)
    monkeypatch.setattr(embeddings, "from_config", lambda config: backend)


def _config_for(tmp_path: Path) -> CodeIndexConfig:
    return CodeIndexConfig(
        version=">=0.1,<1.0",
        project=tmp_path.name,
        roots=["."],
        ignores=[],
        languages=["python"],
        extra_languages=[],
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=32,
    )


def _row_counts(tmp_path: Path) -> dict[str, int]:
    """Snapshot all six indexer-owned tables for equality checks."""
    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = open_index(db_path)
    try:
        out: dict[str, int] = {}
        for table in (
            "chunks",
            "chunks_fts",
            "embeddings",
            "symbols",
            "edges",
            "files",
        ):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            out[table] = int(row[0]) if row is not None else 0
        return out
    finally:
        conn.close()


def _build_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CodeIndexConfig, FakeBackend]:
    """Lay down a two-file project + init + build; chdir into it."""
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta", encoding="utf-8")
    write_skeleton(tmp_path, project_name=None, force=False)

    plugin = _make_plugin()
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugin, backend)

    config = _config_for(tmp_path)
    indexer.build(config, tmp_path)

    # _invoke / the CLI uses Path.cwd() for upward config discovery.
    monkeypatch.chdir(tmp_path)
    return config, backend


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke through the boundary handler so envelopes hit stdout."""
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_rebuild_happy_path_row_counts_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index rebuild --yes`` repopulates every table; counts match build."""
    _build_fixture(tmp_path, monkeypatch)
    before: dict[str, int] = _row_counts(tmp_path)
    # Sanity: build produced data in every relevant table.
    for table, count in before.items():
        assert count > 0, (
            f"expected >0 rows in {table} after build; counts={before}"
        )

    exit_code, stdout, _stderr = _run(["index", "rebuild", "--yes"], capsys)
    assert exit_code == 0, stdout

    # Same one-line text summary shape as `index build`.
    assert "indexed" in stdout
    assert "files" in stdout
    assert "chunks" in stdout

    after: dict[str, int] = _row_counts(tmp_path)
    assert after == before, (
        f"rebuild row counts diverged: before={before}, after={after}"
    )


# ---------------------------------------------------------------------------
# 2. Missing --yes
# ---------------------------------------------------------------------------


def test_rebuild_without_yes_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``--yes`` -> exit 1, ``kind == "usage.confirmation_required"``."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, stderr = _run(
        ["--format", "json", "index", "rebuild"], capsys
    )

    assert exit_code == 1
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["code"] == 1
    assert error["kind"] == "usage.confirmation_required"
    assert "--yes" in error["message"]
    # Human summary mirrors the envelope on stderr.
    assert "--yes" in stderr
    assert "usage.confirmation_required" in stderr


def test_rebuild_without_yes_text_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Text mode: stdout empty; stderr carries the ``--yes`` hint."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, stderr = _run(["index", "rebuild"], capsys)
    assert exit_code == 1
    assert stdout == ""
    assert "--yes" in stderr
    assert "usage.confirmation_required" in stderr


# ---------------------------------------------------------------------------
# 3. JSON summary shape
# ---------------------------------------------------------------------------


def test_rebuild_json_summary_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` matches the pinned ``index build`` IndexerResult shape."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "rebuild", "--yes"], capsys
    )
    assert exit_code == 0, stdout
    payload: dict[str, Any] = json.loads(stdout)

    assert set(payload.keys()) == {
        "files_walked",
        "files_chunked",
        "chunks_inserted",
        "symbols_inserted",
        "edges_inserted",
        "seconds_elapsed",
    }
    for key in (
        "files_walked",
        "files_chunked",
        "chunks_inserted",
        "symbols_inserted",
        "edges_inserted",
    ):
        assert isinstance(payload[key], int), (key, payload[key])
    assert isinstance(payload["seconds_elapsed"], float)

    # The fixture has two `.py` files, each producing one chunk.
    assert payload["files_walked"] == 2
    assert payload["files_chunked"] == 2
    assert payload["chunks_inserted"] == 2


# ---------------------------------------------------------------------------
# 4. No pre-flight model check
# ---------------------------------------------------------------------------


def test_rebuild_skips_pre_flight_model_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A mismatched stored ``embed_model`` does NOT block rebuild.

    Per ``context.md`` decision 7 and ``002.context.md``: rebuild is
    about to drop the data anyway, so it MUST NOT raise
    ``index.embed_model_mismatch``. After the rebuild, ``meta.embed_model``
    reflects the configured backend (the Phase 4 auto-rebuild drop
    sequence resets the indexer-owned meta keys, and the post-pipeline
    ``set_meta`` writes the backend's ``name``).
    """
    _build_fixture(tmp_path, monkeypatch)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = open_index(db_path)
    try:
        set_meta(conn, "embed_model", "wrong:model")
        conn.commit()
    finally:
        conn.close()

    # Sanity-check the corruption took.
    conn = open_index(db_path)
    try:
        assert get_meta(conn, "embed_model") == "wrong:model"
    finally:
        conn.close()

    exit_code, stdout, _stderr = _run(["index", "rebuild", "--yes"], capsys)
    assert exit_code == 0, stdout

    conn = open_index(db_path)
    try:
        # FakeBackend.name == "fake:tiny" (the configured backend's name).
        assert get_meta(conn, "embed_model") == "fake:tiny"
        assert get_meta(conn, "embed_dim") == str(_EMBED_DIM)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. No index yet — rebuild degenerates to build.
# ---------------------------------------------------------------------------


def test_rebuild_no_index_yet_degenerates_to_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index rebuild --yes`` with config but no ``index.sqlite`` -> exit 0.

    ``indexer.build`` creates the index file on first run, so rebuild
    from nothing equals build from nothing.
    """
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
    write_skeleton(tmp_path, project_name=None, force=False)

    plugin = _make_plugin()
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugin, backend)
    monkeypatch.chdir(tmp_path)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    assert not db_path.exists(), "precondition: no index.sqlite yet"

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "rebuild", "--yes"], capsys
    )
    assert exit_code == 0, stdout

    payload: dict[str, Any] = json.loads(stdout)
    assert payload["files_walked"] == 1
    assert payload["files_chunked"] == 1
    assert payload["chunks_inserted"] == 1

    # Index file now exists and carries the expected meta.
    assert db_path.exists()
    conn = open_index(db_path)
    try:
        assert get_meta(conn, "embed_model") == "fake:tiny"
        assert get_meta(conn, "embed_dim") == str(_EMBED_DIM)
    finally:
        conn.close()
