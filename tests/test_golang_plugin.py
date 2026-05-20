"""Tests for the Go language plugin.

Covers the contract from ``docs/plans/003.language-plugins/006.go-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/golang/sample.go``; the surface tests check the
static API; the method-receiver test asserts the scope-composition rule; the
malformed-input test exercises tree-sitter's error-recovery path.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.golang import LANGUAGE

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "golang" / "sample.go"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".go",)


def test_name() -> None:
    assert LANGUAGE.name == "go"


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


def test_method_receiver_in_scope() -> None:
    """Method chunks must carry ``<pkg>.<ReceiverType>`` as ``scope``.

    Both pointer and value receivers strip the asterisk and produce the
    same scope ("widgets.Frobnicator" for the fixture). The matching symbol
    name is ``<pkg>.<ReceiverType>.<MethodName>``.
    """
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = LANGUAGE.chunk(FIXTURE, content)
    methods = [c for c in chunks if c.kind == "function" and c.scope is not None]
    assert methods, "expected at least one method chunk with a scope"
    for c in methods:
        assert c.scope == "widgets.Frobnicator"
        assert "Frobnicator" in c.scope

    symbols = LANGUAGE.symbols(FIXTURE, content)
    method_symbols = {s.name for s in symbols if s.name.startswith("widgets.Frobnicator.")}
    assert "widgets.Frobnicator.Run" in method_symbols
    assert "widgets.Frobnicator.Render" in method_symbols


def test_malformed_does_not_raise() -> None:
    # Truncated mid-declaration: tree-sitter recovers and the plugin should
    # return a (possibly empty) list rather than raising.
    bad = "package broken\n\nfunc Frob("
    path = Path("broken.go")
    chunk_result = LANGUAGE.chunk(path, bad)
    symbol_result = LANGUAGE.symbols(path, bad)
    import_result = LANGUAGE.imports(path, bad)
    assert isinstance(chunk_result, list)
    assert isinstance(symbol_result, list)
    assert isinstance(import_result, list)
