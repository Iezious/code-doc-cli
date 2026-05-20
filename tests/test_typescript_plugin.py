"""Tests for the TypeScript language plugin.

Covers the contract from ``docs/plans/003.language-plugins/005.typescript-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/typescript/sample.ts``; the three identity tests
check the static surface; ``test_type_only_import_tagged`` checks that
``import type ...`` is tagged in edge meta; the malformed-input test
exercises tree-sitter's error-recovery path.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.typescript import LANGUAGE

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "typescript" / "sample.ts"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".ts", ".tsx")


def test_name() -> None:
    assert LANGUAGE.name == "typescript"


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


def test_type_only_import_tagged() -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    edges = LANGUAGE.imports(FIXTURE, content)
    type_only_edges = [e for e in edges if e.meta and e.meta.get("type_only") is True]
    assert len(type_only_edges) == 1
    edge = type_only_edges[0]
    assert edge.target == "react"
    assert edge.meta is not None
    assert edge.meta["type_only"] is True
    assert edge.meta["names"] == ["ReactNode"]


def test_malformed_does_not_raise() -> None:
    # Truncated mid-declaration: tree-sitter recovers and the plugin should
    # return a (possibly empty) list rather than raising.
    bad = "import type { Foo } from \"./types\";\nexport interface Broken<\n"
    path = Path("broken.ts")
    chunk_result = LANGUAGE.chunk(path, bad)
    symbol_result = LANGUAGE.symbols(path, bad)
    import_result = LANGUAGE.imports(path, bad)
    assert isinstance(chunk_result, list)
    assert isinstance(symbol_result, list)
    assert isinstance(import_result, list)
