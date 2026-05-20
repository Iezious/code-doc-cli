"""Tests for the JavaScript language plugin.

Covers the contract from ``docs/plans/003.language-plugins/004.javascript-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/javascript/sample.js``; the three identity tests
check the static surface; the synthetic-default-name test exercises both
named and anonymous default-export forms via inline source strings; the
malformed-input test exercises tree-sitter's error-recovery path.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.javascript import LANGUAGE

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "javascript" / "sample.js"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".js", ".mjs", ".cjs")


def test_name() -> None:
    assert LANGUAGE.name == "javascript"


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


def test_default_export_synthetic_name_named() -> None:
    # Even when the inner declaration carries an identifier, the symbol is the
    # synthetic ``default::<stem>`` form — the export name is "default".
    path = Path("widget.js")
    content = "export default function foo() {}\n"
    syms = LANGUAGE.symbols(path, content)
    assert len(syms) == 1
    assert syms[0].name == "default::widget"
    assert syms[0].kind == "def"
    assert syms[0].line == 1


def test_default_export_synthetic_name_anonymous_arrow() -> None:
    path = Path("index.js")
    content = "export default () => 1;\n"
    syms = LANGUAGE.symbols(path, content)
    assert len(syms) == 1
    assert syms[0].name == "default::index"
    assert syms[0].kind == "def"
    assert syms[0].line == 1


def test_malformed_does_not_raise() -> None:
    # Truncated mid-declaration: tree-sitter recovers and the plugin should
    # return a (possibly empty) list rather than raising.
    bad = "import { useState } from \"react\";\nexport function broken(\n"
    path = Path("broken.js")
    chunk_result = LANGUAGE.chunk(path, bad)
    symbol_result = LANGUAGE.symbols(path, bad)
    import_result = LANGUAGE.imports(path, bad)
    assert isinstance(chunk_result, list)
    assert isinstance(symbol_result, list)
    assert isinstance(import_result, list)
