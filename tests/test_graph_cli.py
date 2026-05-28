"""Tests for the ``code_index graph callers|deps`` CLI wrappers.

Covers the six cases pinned in
``docs/plans/006.sync-symbols-graph/004.graph.md`` "Tests":

1. Missing index -> exit 12, ``kind == "index.missing"``.
2. Embed-model mismatch -> exit 11, ``kind == "index.embed_model_mismatch"``.
3. JSON shape (callers) — list of objects with exactly the documented keys.
4. JSON shape (deps) — list of objects with exactly the documented keys.
5. Text shape — one line per hit for both subcommands.
6. Empty result — exit 0, ``[]`` under JSON / empty stdout under text, both
   subcommands.

Drives the CLI through :func:`code_index.cli._invoke` so the boundary
handler routes :class:`CodeIndexError` envelopes to stdout (matches the
pattern in ``tests/test_symbols_cli.py``).
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
    """Two python files:

    - ``main.py`` (single chunk, scope ``main``): two edges — an ``import os``
      and a ``call Foo``.
    - ``foo.py`` (single chunk, scope ``mod.Foo``): one edge — ``call bar``.

    The ``Foo`` call edge in ``main.py`` is the target the ``graph callers``
    JSON test queries (substring ``Foo``).
    """
    return FakePlugin(
        name="python",
        extensions=(".py",),
        chunks_by_path={
            "main.py": [
                Chunk(
                    start_line=1,
                    end_line=1,
                    kind="function",
                    name="main",
                    scope="main",
                    text="Foo(); import os",
                )
            ],
            "foo.py": [
                Chunk(
                    start_line=10,
                    end_line=10,
                    kind="function",
                    name="Foo",
                    scope="mod.Foo",
                    text="def Foo(): bar()",
                )
            ],
        },
        symbols_by_path={
            "main.py": [Symbol(name="main", kind="def", line=1)],
            "foo.py": [Symbol(name="Foo", kind="def", line=10)],
        },
        edges_by_path={
            "main.py": [
                Edge(target="os", kind="import", line=1, meta=None),
                Edge(target="Foo", kind="call", line=1, meta=None),
            ],
            "foo.py": [
                Edge(target="bar", kind="call", line=10, meta={"note": "hi"}),
            ],
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
    (tmp_path / "main.py").write_text("Foo(); import os", encoding="utf-8")
    (tmp_path / "foo.py").write_text("def Foo(): bar()", encoding="utf-8")
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
        ["--format", "json", "graph", "callers", "Foo"], capsys
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
        ["--format", "json", "graph", "deps", "main.py"], capsys
    )

    assert exit_code == 11
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["kind"] == "index.embed_model_mismatch"
    assert error["code"] == 11
    assert "code_index index rebuild" in error["message"]


# ---------------------------------------------------------------------------
# 3. JSON shape — callers
# ---------------------------------------------------------------------------


def test_callers_json_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph callers Foo --format json`` lands a JSON list with the pinned keys."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "graph", "callers", "Foo"], capsys
    )
    assert exit_code == 0, stdout
    payload = json.loads(stdout)
    assert isinstance(payload, list)
    # ``main.py``'s ``Foo`` call edge is the sole match for substring ``Foo``.
    assert len(payload) == 1
    row: dict[str, Any] = payload[0]
    assert set(row.keys()) == {
        "path",
        "scope",
        "language",
        "start_line",
        "kind",
        "dst_name",
    }
    assert row["path"] == "main.py"
    assert row["scope"] == "main"
    assert row["language"] == "python"
    assert row["start_line"] == 1
    assert row["kind"] == "call"
    assert row["dst_name"] == "Foo"


# ---------------------------------------------------------------------------
# 4. JSON shape — deps
# ---------------------------------------------------------------------------


def test_deps_json_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph deps main.py --format json`` lands a JSON list with the pinned keys."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "graph", "deps", "main.py"], capsys
    )
    assert exit_code == 0, stdout
    payload = json.loads(stdout)
    assert isinstance(payload, list)
    # Two edges from ``main.py``: a ``call Foo`` and an ``import os``.
    assert len(payload) == 2
    for row in payload:
        assert set(row.keys()) == {"path", "kind", "dst_name", "meta"}
        assert row["path"] == "main.py"
        # Both edges in ``main.py`` were inserted with ``meta=None``.
        assert row["meta"] is None
    dst_names = sorted(row["dst_name"] for row in payload)
    assert dst_names == ["Foo", "os"]


# ---------------------------------------------------------------------------
# 5. Text shape
# ---------------------------------------------------------------------------


def test_text_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default text mode emits one line per hit for both subcommands."""
    _build_fixture(tmp_path, monkeypatch)

    # graph callers Foo -> one line for the main.py call site.
    code_c, stdout_c, _err_c = _run(["graph", "callers", "Foo"], capsys)
    assert code_c == 0, stdout_c
    lines_c: list[str] = [
        line for line in stdout_c.splitlines() if line.strip()
    ]
    assert len(lines_c) == 1
    assert "main.py:1" in lines_c[0]
    assert "Foo" in lines_c[0]
    assert "call" in lines_c[0]
    # ``main`` is the chunk scope and must appear in the text rendering.
    assert "main" in lines_c[0]

    # graph deps main.py -> two lines (call Foo, import os).
    code_d, stdout_d, _err_d = _run(["graph", "deps", "main.py"], capsys)
    assert code_d == 0, stdout_d
    lines_d: list[str] = [
        line for line in stdout_d.splitlines() if line.strip()
    ]
    assert len(lines_d) == 2
    # Both lines start with the path.
    assert all(line.startswith("main.py") for line in lines_d)
    # The two targets appear somewhere across the two lines.
    joined: str = "\n".join(lines_d)
    assert "Foo" in joined
    assert "os" in joined


# ---------------------------------------------------------------------------
# 6. Empty result — both subcommands, both formats
# ---------------------------------------------------------------------------


def test_empty_result_callers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph callers`` against an absent symbol returns ``[]`` / empty."""
    _build_fixture(tmp_path, monkeypatch)

    code_j, stdout_j, _err_j = _run(
        [
            "--format",
            "json",
            "graph",
            "callers",
            "zzzz_not_present_zzzz",
            "--exact",
        ],
        capsys,
    )
    assert code_j == 0, stdout_j
    assert json.loads(stdout_j) == []

    code_t, stdout_t, _err_t = _run(
        ["graph", "callers", "zzzz_not_present_zzzz", "--exact"], capsys
    )
    assert code_t == 0, stdout_t
    assert stdout_t == ""


def test_empty_result_deps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``graph deps`` against an absent path returns ``[]`` / empty."""
    _build_fixture(tmp_path, monkeypatch)

    code_j, stdout_j, _err_j = _run(
        ["--format", "json", "graph", "deps", "does/not/exist.py"], capsys
    )
    assert code_j == 0, stdout_j
    assert json.loads(stdout_j) == []

    code_t, stdout_t, _err_t = _run(
        ["graph", "deps", "does/not/exist.py"], capsys
    )
    assert code_t == 0, stdout_t
    assert stdout_t == ""
