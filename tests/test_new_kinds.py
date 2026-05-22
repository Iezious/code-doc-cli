"""Tests for the two new ``Kinds`` constants added by Phase 7 step 004.

Covers the DoD bullets from
``docs/plans/007.config-show-json-polish/004.kinds-formalize.md`` "Tests":

1. :attr:`Kinds.USAGE_CONFIRMATION_REQUIRED` is registered.
2. :attr:`Kinds.CLI_BAD_ENUM` is registered.
3. ``index rebuild`` without ``--yes`` emits ``kind ==
   "usage.confirmation_required"`` and exit 1 under ``--format json``
   (envelope sourced from the registry constant — kind string unchanged
   from Phase 6).
4. ``search --mode garbage`` emits ``kind == "cli.bad_enum"`` and exit 1
   under ``--format json``; ``detail.expected`` carries the allowed set.
5. ``search --mode hybrid`` still works (regression check on the
   enum-validation rewrite — exit 0, ``{"results": [...]}`` shape).

The two CLI-driven cases use the rebuild-CLI fixture pattern (fake
plugin + fake backend, no fastembed download) so the suite stays fast.
The bad-mode and happy-path search tests share the same fake-backed
index. Tests drive the CLI through :func:`code_index.cli._invoke` so the
Phase 1 boundary handler routes :class:`CodeIndexError` envelopes to
stdout (matches the pattern in ``tests/test_rebuild_cli.py`` and
``tests/test_search_cli.py``).
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
from code_index.errors import Kinds
from code_index.init import write_skeleton
from code_index.languages import Chunk, Edge, Symbol
from code_index.languages.registry import LanguageRegistry

_EMBED_DIM: int = 768


# ---------------------------------------------------------------------------
# Fake plugin / backend doubles (mirror tests/test_rebuild_cli.py).
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
# 1 & 2. Registry constants exist with the documented dotted strings.
# ---------------------------------------------------------------------------


def test_usage_confirmation_required_kind_registered() -> None:
    """:attr:`Kinds.USAGE_CONFIRMATION_REQUIRED` carries the dotted string."""
    assert Kinds.USAGE_CONFIRMATION_REQUIRED == "usage.confirmation_required"


def test_cli_bad_enum_kind_registered() -> None:
    """:attr:`Kinds.CLI_BAD_ENUM` carries the dotted string."""
    assert Kinds.CLI_BAD_ENUM == "cli.bad_enum"


# ---------------------------------------------------------------------------
# 3. `index rebuild` without `--yes` emits the registered kind.
# ---------------------------------------------------------------------------


def test_rebuild_without_yes_emits_registered_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``--yes`` -> exit 1, ``kind == Kinds.USAGE_CONFIRMATION_REQUIRED``.

    Same envelope shape as Phase 6's test; this case verifies that the
    raise-site swap (literal -> registry constant) preserves the wire
    contract.
    """
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "index", "rebuild"], capsys
    )
    assert exit_code == 1
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["code"] == 1
    assert error["kind"] == Kinds.USAGE_CONFIRMATION_REQUIRED
    assert error["kind"] == "usage.confirmation_required"


# ---------------------------------------------------------------------------
# 4. `search --mode garbage` emits cli.bad_enum (code 1).
# ---------------------------------------------------------------------------


def test_search_bad_mode_emits_cli_bad_enum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--mode garbage`` -> exit 1, ``kind == "cli.bad_enum"``, detail has expected set."""
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "search", "foo", "--mode", "garbage"], capsys
    )
    assert exit_code == 1
    envelope: dict[str, Any] = json.loads(stdout)
    error: dict[str, Any] = envelope["error"]
    assert error["code"] == 1
    assert error["kind"] == Kinds.CLI_BAD_ENUM
    assert error["kind"] == "cli.bad_enum"
    detail: dict[str, Any] = error["detail"]
    assert detail["flag"] == "--mode"
    assert detail["value"] == "garbage"
    assert "hybrid" in detail["expected"]
    assert set(detail["expected"]) == {"bm25", "dense", "hybrid"}


# ---------------------------------------------------------------------------
# 5. `search --mode hybrid` still works (regression check).
# ---------------------------------------------------------------------------


def test_search_mode_hybrid_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--mode hybrid`` returns the ``{"results": [...]}`` shape, exit 0.

    Verifies the enum-validation rewrite did not regress the happy path.
    The fake backend yields zero-vectors so ``search_module.search`` may
    return zero or more rows; only the document shape is asserted.
    """
    _build_fixture(tmp_path, monkeypatch)

    exit_code, stdout, _stderr = _run(
        ["--format", "json", "search", "alpha", "--mode", "hybrid"], capsys
    )
    assert exit_code == 0, stdout
    payload: dict[str, Any] = json.loads(stdout)
    assert "results" in payload
    assert isinstance(payload["results"], list)
