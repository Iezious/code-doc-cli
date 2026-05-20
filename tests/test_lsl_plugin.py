"""Tests for the LSL language plugin.

Covers the contract from ``docs/plans/003.language-plugins/008.lsl-plugin.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/lsl/sample.lsl``; the OSSL-absence test is the
critical regression gate (no ``osXxx`` identifier may surface as a symbol or
edge). Phase 3 LSL is pure LSL — OSSL recognition is deferred (see
``outcome.md``).
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.lsl import LANGUAGE, LSLPlugin

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "lsl" / "sample.lsl"


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".lsl",)


def test_name() -> None:
    assert LANGUAGE.name == "lsl"


def test_runtime_checkable() -> None:
    assert isinstance(LANGUAGE, Language)


def test_chunk_snapshot(snapshot) -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.chunk(FIXTURE, content) == snapshot


def test_symbol_snapshot(snapshot) -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.symbols(FIXTURE, content) == snapshot


def test_import_snapshot(snapshot) -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.imports(FIXTURE, content) == snapshot


def test_no_ossl_recognition() -> None:
    """``osXxx`` calls must not surface as symbols or edges.

    The fixture intentionally contains both ``llSay(0, "ready")`` and
    ``osSetSpeed(1.0)``. The plugin's ``ll``-prefixed regex (``\\bll[A-Z]...``)
    excludes ``os`` prefixes structurally; this test is the regression gate.
    """
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")

    symbols = plugin.symbols(FIXTURE, content)
    edges = plugin.imports(FIXTURE, content)

    sym_names = [s.name for s in symbols]
    edge_targets = [e.target for e in edges]

    # llSay is present as a ``ref`` symbol.
    assert "llSay" in sym_names

    # No osXxx anywhere — neither as a symbol name nor as part of any edge
    # target or kind.
    assert not any("os" in s.name and s.name[:2] == "os" for s in symbols)
    assert not any(s.name == "osSetSpeed" for s in symbols)
    assert not any(t.startswith("os") for t in edge_targets)
    assert not any(e.kind.startswith("os") for e in edges)


def test_listen_edge() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    edges = plugin.imports(FIXTURE, content)
    listen = [e for e in edges if e.kind == "listen"]
    assert len(listen) == 1
    assert listen[0].target == "42"


def test_link_message_edge() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    edges = plugin.imports(FIXTURE, content)
    link_msgs = [e for e in edges if e.kind == "link_message"]
    assert len(link_msgs) == 1
    # ``llMessageLinked(LINK_THIS, 1, "touched", "")`` — target is the
    # ``number`` argument's source text, i.e. ``"1"``? No — the step says
    # ``target=<number-arg-text>`` where number is the SECOND argument. But
    # 008.context.md's "Edges — argument extraction" specifies the FIRST
    # argument verbatim for all four edge-producing calls. The context doc
    # is the authoritative tie-breaker here.
    assert link_msgs[0].target == "LINK_THIS"


def test_http_edge() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    edges = plugin.imports(FIXTURE, content)
    http = [e for e in edges if e.kind == "http"]
    assert len(http) == 1
    # First-argument-verbatim rule includes the surrounding quotes.
    assert http[0].target == '"https://example.invalid/x"'


def test_email_edge() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    edges = plugin.imports(FIXTURE, content)
    email = [e for e in edges if e.kind == "email"]
    assert len(email) == 1
    assert email[0].target == '"dest@example.invalid"'


def test_event_handler_chunked_with_state_scope() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(FIXTURE, content)
    touch_starts = [
        c for c in chunks if c.kind == "event" and c.name == "touch_start"
    ]
    assert len(touch_starts) == 1
    assert touch_starts[0].scope == "default"


def test_event_handler_in_named_state() -> None:
    """The ``state idle`` block exposes its own ``state_entry`` event.

    Both states declare a ``state_entry``; the symbol form ``<state>.<event>``
    disambiguates them.
    """
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    sym_names = {s.name for s in plugin.symbols(FIXTURE, content)}
    assert "default.state_entry" in sym_names
    assert "idle.state_entry" in sym_names


def test_function_chunk_has_global_scope() -> None:
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(FIXTURE, content)
    funcs = [c for c in chunks if c.kind == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "add"
    assert funcs[0].scope == "global"


def test_module_chunk_for_globals() -> None:
    """Exactly one ``module`` chunk wraps the global variable declarations."""
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(FIXTURE, content)
    modules = [c for c in chunks if c.kind == "module"]
    assert len(modules) == 1
    assert modules[0].name is None
    assert modules[0].scope is None


def test_ref_symbols_one_per_occurrence() -> None:
    """``llSay`` is called twice in the fixture; both occurrences must surface."""
    plugin = LSLPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    say_refs = [
        s for s in plugin.symbols(FIXTURE, content)
        if s.name == "llSay" and s.kind == "ref"
    ]
    assert len(say_refs) == 2


def test_malformed_does_not_raise() -> None:
    bad = "default { state_entry() { llListen(\nstate idle { } }"
    path = Path("broken.lsl")
    plugin = LSLPlugin()
    # Must not raise; results may be empty or best-effort.
    plugin.chunk(path, bad)
    plugin.symbols(path, bad)
    plugin.imports(path, bad)
