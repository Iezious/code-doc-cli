"""Tests for the ``code_index index sync`` CLI wrapper.

Covers the four scenarios pinned in
``docs/plans/006.sync-symbols-graph/001.sync-engine.md`` "Tests":

1. Missing index -> exit 12, ``kind == "index.missing"``.
2. Embed-model mismatch -> exit 11, ``kind == "index.embed_model_mismatch"``.
3. Embed-dim mismatch -> exit 11, ``kind == "index.embed_dim_mismatch"``.
4. JSON summary shape matches ``context.md``.

Tests that assert the JSON error envelope drive the CLI through
:func:`code_index.cli._invoke` so the Phase 1 boundary handler routes
the :class:`CodeIndexError` to stdout (matches the pattern in
``tests/test_search_cli.py`` and ``tests/test_index_build_cli.py``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from code_index import embeddings, indexer, walker
from code_index import sync as sync_module
from code_index.cli import _invoke
from code_index.config import CodeIndexConfig
from code_index.init import write_skeleton
from code_index.languages import Chunk, Edge, Symbol
from code_index.languages.registry import LanguageRegistry
from code_index.storage import open_index, set_meta

_EMBED_DIM: int = 768


# ---------------------------------------------------------------------------
# Fake plugin / backend doubles (kept local to avoid coupling test files)
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
            ]
        },
        symbols_by_path={"a.py": [Symbol(name="alpha", kind="def", line=1)]},
        edges_by_path={
            "a.py": [Edge(target="dep", kind="import", line=1, meta=None)]
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
    monkeypatch.setattr(sync_module, "active_plugins", lambda config: registry)
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


def _build_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CodeIndexConfig, FakeBackend]:
    """Lay down a one-file project + init + build; chdir into it."""
    (tmp_path / "a.py").write_text("alpha", encoding="utf-8")
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
# 1. Missing index
# ---------------------------------------------------------------------------


def test_missing_index_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``index sync`` with config but no index.sqlite -> exit 12."""
    write_skeleton(tmp_path, project_name=None, force=False)
    monkeypatch.chdir(tmp_path)

    # Avoid loading the real fastembed model if pre-flight tried to.
    fake = FakeBackend()
    monkeypatch.setattr(embeddings, "from_config", lambda config: fake)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "sync"], capsys
    )

    assert exit_code == 12
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.missing"
    assert error["code"] == 12
    assert "code_index index build" in error["message"]


# ---------------------------------------------------------------------------
# 2. Embed-model mismatch
# ---------------------------------------------------------------------------


def test_embed_model_mismatch_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stored ``embed_model`` differing from backend.name -> exit 11."""
    _build_fixture(tmp_path, monkeypatch)

    # Force a mismatch on the persisted meta key.
    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = open_index(db_path)
    try:
        set_meta(conn, "embed_model", "other:model")
        conn.commit()
    finally:
        conn.close()

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "sync"], capsys
    )

    assert exit_code == 11
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.embed_model_mismatch"
    assert error["code"] == 11
    assert "code_index index rebuild" in error["message"]


# ---------------------------------------------------------------------------
# 3. Embed-dim mismatch
# ---------------------------------------------------------------------------


def test_embed_dim_mismatch_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stored ``embed_dim`` differing from str(backend.dim) -> exit 11."""
    _build_fixture(tmp_path, monkeypatch)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = open_index(db_path)
    try:
        set_meta(conn, "embed_dim", "512")
        conn.commit()
    finally:
        conn.close()

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "sync"], capsys
    )

    assert exit_code == 11
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.embed_dim_mismatch"
    assert error["code"] == 11
    assert "code_index index rebuild" in error["message"]


# ---------------------------------------------------------------------------
# 4. JSON summary shape
# ---------------------------------------------------------------------------


def test_json_summary_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdout under ``--format json`` matches the pinned ``index sync`` shape."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "sync"], capsys
    )
    assert exit_code == 0, stdout
    payload: dict[str, Any] = json.loads(stdout)

    assert set(payload.keys()) == {
        "files_added",
        "files_changed",
        "files_unchanged",
        "files_removed",
        "chunks_inserted_total",
        "seconds_elapsed",
    }
    for key in (
        "files_added",
        "files_changed",
        "files_unchanged",
        "files_removed",
        "chunks_inserted_total",
    ):
        assert isinstance(payload[key], int), (key, payload[key])
    assert isinstance(payload["seconds_elapsed"], float)

    # Sync immediately after build -> only ``files_unchanged`` is nonzero.
    assert payload["files_added"] == 0
    assert payload["files_changed"] == 0
    assert payload["files_removed"] == 0
    assert payload["files_unchanged"] == 1
    assert payload["chunks_inserted_total"] == 0


# ---------------------------------------------------------------------------
# Bonus: text-mode summary touches stdout (smoke-tests the human path).
# ---------------------------------------------------------------------------


def test_text_summary_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default ``--format text`` summary lands on stdout as one line."""
    _build_fixture(tmp_path, monkeypatch)

    # Add a new file so the summary mentions ``+1``.
    new_path: Path = tmp_path / "b.py"
    new_path.write_text("beta", encoding="utf-8")

    # The fake plugin's chunks_by_path needs an entry for the new file too;
    # rebuild the registry the patched modules already point at by mutating
    # the existing dict (the closure in _patch_pipeline returned the same
    # registry on every call so the indexer/sync share state).
    # Simpler: re-patch with a richer plugin.
    plugin = FakePlugin(
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
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugin, backend)

    exit_code, stdout, _stderr = _run(["index", "sync"], capsys)
    assert exit_code == 0, stdout
    assert "synced:" in stdout
    assert "+1" in stdout
    # Touch os.stat to keep the import non-superfluous if anyone trims it later.
    assert os.path.exists(new_path)
