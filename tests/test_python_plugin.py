"""Tests for the Python language plugin.

Covers the contract from ``docs/plans/003.language-plugins/002.python-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/python/sample.py``; the three identity tests check
the static surface; the malformed-input test exercises the ``SyntaxError``
guard.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.python import LANGUAGE

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "python" / "sample.py"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".py",)


def test_name() -> None:
    assert LANGUAGE.name == "python"


def test_runtime_checkable() -> None:
    assert isinstance(LANGUAGE, Language)


def test_chunk_snapshot(snapshot) -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    assert LANGUAGE.chunk(FIXTURE, content) == snapshot


def test_symbol_snapshot(snapshot) -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    assert LANGUAGE.symbols(FIXTURE, content) == snapshot


def test_import_snapshot(snapshot) -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    assert LANGUAGE.imports(FIXTURE, content) == snapshot


def test_malformed_does_not_raise() -> None:
    bad = "def broken(:\n"
    path = Path("broken.py")
    assert LANGUAGE.chunk(path, bad) == []
    assert LANGUAGE.symbols(path, bad) == []
    assert LANGUAGE.imports(path, bad) == []
