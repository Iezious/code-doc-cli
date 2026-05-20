"""Tests for the F# language plugin.

Covers the contract from ``docs/plans/003.language-plugins/007.fsharp-plugin.md``
plus the hybrid ``.fsproj`` discovery direction from the feature ``context.md``.
Chunk / symbol / edge output is locked via syrupy snapshots against
``tests/fixtures/languages/fsharp/sample.fs``; the static surface tests pin
the Protocol shape; the warn-and-degrade tests exercise the missing-``.fsproj``
path; the constructor-override tests pin the hybrid behavior.
"""

from __future__ import annotations

from pathlib import Path

from code_index.languages import Language
from code_index.languages.fsharp import LANGUAGE, FSharpPlugin

FIXTURE = Path(__file__).parent / "fixtures" / "languages" / "fsharp" / "sample.fs"
FSPROJ = Path(__file__).parent / "fixtures" / "languages" / "fsharp" / "sample.fsproj"
NO_PROJ_FIXTURE = (
    Path(__file__).parent / "fixtures" / "languages" / "fsharp_no_proj" / "sample.fs"
)


def test_extensions() -> None:
    assert LANGUAGE.extensions == (".fs", ".fsi", ".fsx")


def test_name() -> None:
    assert LANGUAGE.name == "fsharp"


def test_runtime_checkable() -> None:
    assert isinstance(LANGUAGE, Language)


def test_chunk_snapshot(snapshot) -> None:
    plugin = FSharpPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.chunk(FIXTURE, content) == snapshot


def test_symbol_snapshot(snapshot) -> None:
    plugin = FSharpPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.symbols(FIXTURE, content) == snapshot


def test_import_snapshot(snapshot) -> None:
    plugin = FSharpPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    assert plugin.imports(FIXTURE, content) == snapshot


def test_uses_fsproj_order() -> None:
    """At least one chunk records the ``.fsproj`` compile-order index.

    Storage form: appended to ``Chunk.scope`` as ``|fsproj=<N>`` (Option A
    from ``007.context.md``). A storage-form regression should trigger this
    explicit assertion, not just a snapshot diff.
    """
    plugin = FSharpPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(FIXTURE, content)
    assert any(c.scope is not None and "|fsproj=0" in c.scope for c in chunks), (
        "expected at least one chunk to carry |fsproj=0 in its scope"
    )


def test_warns_without_fsproj(capsys) -> None:
    plugin = FSharpPlugin()
    content = NO_PROJ_FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(NO_PROJ_FIXTURE, content)
    captured = capsys.readouterr()
    # Warning emitted to stderr.
    assert ".fsproj" in captured.err
    # The warn path does not zero the output — chunks are still produced.
    assert chunks, "expected chunks even without an .fsproj"


def test_discriminated_union_cases_as_symbols() -> None:
    plugin = FSharpPlugin()
    content = FIXTURE.read_text(encoding="utf-8")
    names = {s.name for s in plugin.symbols(FIXTURE, content)}
    # The type itself and every case as separate symbols.
    assert "MyCorp.Geometry.Color" in names
    assert "MyCorp.Geometry.Color.Red" in names
    assert "MyCorp.Geometry.Color.Green" in names
    assert "MyCorp.Geometry.Color.Blue" in names


def test_malformed_does_not_raise() -> None:
    # Truly unparseable mush that still happens to contain F#-ish keywords.
    bad = "let [[[ broken ===\nmember <<< wrong\ntype | | |\n"
    path = Path("broken.fs")
    plugin = FSharpPlugin()
    # Must not raise; results may be empty or best-effort.
    plugin.chunk(path, bad)
    plugin.symbols(path, bad)
    plugin.imports(path, bad)


def test_constructor_override_uses_provided_fsproj(capsys) -> None:
    """An explicit ``fsproj_path`` is used directly; no parent walk happens.

    Verifies (a) the chunk for the listed file carries ``|fsproj=0`` (so the
    override mapping was consulted) and (b) no walk-state was populated for
    the file's parent directory (the walk cache is empty).
    """
    plugin = FSharpPlugin(fsproj_path=FSPROJ)
    content = FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(FIXTURE, content)
    assert any(c.scope is not None and "|fsproj=0" in c.scope for c in chunks)
    # No directory-walk cache entries should have been created — override
    # short-circuits discovery entirely.
    assert plugin._dir_to_fsproj == {}
    # Sanity: no warning emitted.
    captured = capsys.readouterr()
    assert ".fsproj" not in captured.err


def test_constructor_override_silences_missing_fsproj_warn(capsys) -> None:
    """With an override, parsing a file outside any ``.fsproj`` does not warn.

    The override means the plugin doesn't walk and so has nothing to warn
    about. The file's chunks simply lack a ``fsproj_order`` suffix.
    """
    plugin = FSharpPlugin(fsproj_path=FSPROJ)
    content = NO_PROJ_FIXTURE.read_text(encoding="utf-8")
    chunks = plugin.chunk(NO_PROJ_FIXTURE, content)
    captured = capsys.readouterr()
    assert ".fsproj" not in captured.err
    # The file is not listed in the override's <Compile Include>, so no
    # |fsproj= suffix should appear.
    assert all(
        c.scope is None or "|fsproj=" not in c.scope for c in chunks
    )
