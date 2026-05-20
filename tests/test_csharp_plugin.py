"""Tests for the C# language plugin.

Covers the contract from ``docs/plans/003.language-plugins/003.csharp-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/csharp/sample.cs``; the three identity tests check
the static surface; the malformed-input test exercises tree-sitter's
error-recovery path.

The fixture deliberately mixes top-level statements with a namespace at file
scope — illegal in production C# but the tree-sitter grammar accepts it
without error, which lets one fixture exercise every chunk kind in this
plugin.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.csharp import LANGUAGE

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "csharp" / "sample.cs"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".cs",)


def test_name() -> None:
    assert LANGUAGE.name == "csharp"


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
    # Truncated mid-declaration: tree-sitter recovers and the plugin should
    # return a (possibly empty) list rather than raising.
    bad = "namespace Broken {\n    public class Frob\n"
    path = Path("broken.cs")
    chunk_result = LANGUAGE.chunk(path, bad)
    symbol_result = LANGUAGE.symbols(path, bad)
    import_result = LANGUAGE.imports(path, bad)
    assert isinstance(chunk_result, list)
    assert isinstance(symbol_result, list)
    assert isinstance(import_result, list)
