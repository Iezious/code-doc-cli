"""Tests for the ``code_index symbols defs|refs`` CLI wrappers.

Covers the five cases pinned in
``docs/plans/006.sync-symbols-graph/003.symbols.md`` "Tests":

1. Missing index -> exit 12, ``kind == "index.missing"``.
2. Embed-model mismatch -> exit 11, ``kind == "index.embed_model_mismatch"``.
3. JSON shape — list of objects with exactly the documented keys.
4. Text shape — one line per hit.
5. Empty result — exit 0, ``[]`` under JSON / empty stdout under text.

Drives the CLI through :func:`code_index.cli._invoke` so the boundary
handler routes :class:`CodeIndexError` envelopes to stdout (matches the
pattern in ``tests/test_sync_cli.py`` / ``tests/test_rebuild_cli.py``).
"""

from __future__ import annotations

import json
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
# Fake plugin / backend doubles
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
    device: str = "cpu"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        return np.zeros((len(texts), self.dim), dtype=np.float32)


def _make_plugin() -> FakePlugin:
    """Two python files: ``foo.py`` with ``Foo`` (scope ``mod.Foo``) and
    ``bar.py`` with ``Bar`` (no scope)."""
    return FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path={
            "foo.py": [
                Chunk(
                    start_line=10,
                    end_line=10,
                    kind="function",
                    name="Foo",
                    scope="mod.Foo",
                    text="def Foo(): pass",
                )
            ],
            "bar.py": [
                Chunk(
                    start_line=20,
                    end_line=20,
                    kind="function",
                    name="Bar",
                    scope=None,
                    text="def Bar(): pass",
                )
            ],
        },
        symbols_by_path={
            "foo.py": [Symbol(name="Foo", kind="def", line=10)],
            "bar.py": [Symbol(name="Bar", kind="def", line=20)],
        },
        edges_by_path={
            "foo.py": [],
            "bar.py": [],
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
    """Lay down two files + init + build; chdir into the project root."""
    (tmp_path / "foo.py").write_text("def Foo(): pass", encoding="utf-8")
    (tmp_path / "bar.py").write_text("def Bar(): pass", encoding="utf-8")
    write_skeleton(tmp_path, project_name=None, force=False)

    plugin = _make_plugin()
    backend = FakeBackend()
    _patch_pipeline(monkeypatch, plugin, backend)

    config = _config_for(tmp_path)
    indexer.build(config, tmp_path)

    monkeypatch.chdir(tmp_path)
    return config, backend


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
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
    """Config but no ``index.sqlite`` -> exit 12 with ``kind=index.missing``."""
    write_skeleton(tmp_path, project_name=None, force=False)
    monkeypatch.chdir(tmp_path)

    fake = FakeBackend()
    monkeypatch.setattr(embeddings, "from_config", lambda config: fake)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "symbols", "defs", "Foo"], capsys
    )

    assert exit_code == 12
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.missing"
    assert error["code"] == 12


# ---------------------------------------------------------------------------
# 2. Embed-model mismatch
# ---------------------------------------------------------------------------


def test_embed_model_mismatch_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stored ``embed_model`` differing from backend -> exit 11."""
    _build_fixture(tmp_path, monkeypatch)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = open_index(db_path)
    try:
        set_meta(conn, "embed_model", "other:model")
        conn.commit()
    finally:
        conn.close()

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "symbols", "defs", "Foo"], capsys
    )

    assert exit_code == 11
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.embed_model_mismatch"
    assert error["code"] == 11
    assert "code_index index rebuild" in error["message"]


# ---------------------------------------------------------------------------
# 3. JSON shape — list of objects, exact key set
# ---------------------------------------------------------------------------


def test_json_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``symbols defs Foo --format json`` lands a JSON list with the pinned keys."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "symbols", "defs", "Foo"], capsys
    )
    assert exit_code == 0, stdout
    payload = json.loads(stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    row: dict[str, Any] = payload[0]
    assert set(row.keys()) == {"path", "scope", "language", "name", "line"}
    assert row["path"] == "foo.py"
    assert row["scope"] == "mod.Foo"
    assert row["language"] == "python"
    assert row["name"] == "Foo"
    assert row["line"] == 10


# ---------------------------------------------------------------------------
# 4. Text shape — one line per hit
# ---------------------------------------------------------------------------


def test_text_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default text mode emits one line per hit; ``<path>:<line>`` + name appear."""
    _build_fixture(tmp_path, monkeypatch)

    # Substring "o" matches both ``Foo`` and ``Bar``? No — substring is
    # case-sensitive; ``oo`` only matches ``Foo``. Pick the substring ``a``
    # to hit ``Bar`` and the substring ``F`` to hit ``Foo``; combine by
    # querying with substring "" — but the empty-string sentinel matches
    # everything as well. Use a two-step assertion: one query returns Foo,
    # one returns Bar, both as text lines.
    exit_code_foo, stdout_foo, _err_foo = _run(
        ["symbols", "defs", "Foo"], capsys
    )
    assert exit_code_foo == 0, stdout_foo
    lines_foo: list[str] = [
        line for line in stdout_foo.splitlines() if line.strip()
    ]
    assert len(lines_foo) == 1
    assert "foo.py:10" in lines_foo[0]
    assert "Foo" in lines_foo[0]
    # ``mod.Foo`` is the scope and must show up in the text rendering.
    assert "mod.Foo" in lines_foo[0]

    exit_code_bar, stdout_bar, _err_bar = _run(
        ["symbols", "defs", "Bar"], capsys
    )
    assert exit_code_bar == 0, stdout_bar
    lines_bar: list[str] = [
        line for line in stdout_bar.splitlines() if line.strip()
    ]
    assert len(lines_bar) == 1
    assert "bar.py:20" in lines_bar[0]
    assert "Bar" in lines_bar[0]


# ---------------------------------------------------------------------------
# 5. Empty result
# ---------------------------------------------------------------------------


def test_empty_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An obviously-absent name yields exit 0; ``[]`` under JSON, empty under text."""
    _build_fixture(tmp_path, monkeypatch)

    # JSON: empty array.
    exit_code_json, stdout_json, _err_json = _run(
        [
            "--format",
            "json",
            "symbols",
            "defs",
            "zzzz_not_present_zzzz",
            "--exact",
        ],
        capsys,
    )
    assert exit_code_json == 0, stdout_json
    assert json.loads(stdout_json) == []

    # Text: empty stdout (no lines).
    exit_code_text, stdout_text, _err_text = _run(
        ["symbols", "defs", "zzzz_not_present_zzzz", "--exact"], capsys
    )
    assert exit_code_text == 0, stdout_text
    assert stdout_text == ""
