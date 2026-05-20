"""Tests for the language plugin registry and the extra-language loader.

Covers the contract from ``docs/plans/003.language-plugins/001.interface-and-registry.md``
Tests section. The seven built-in plugins are placeholders at this step
(see ``001.context.md``) but they still expose the right ``name`` and
``extensions`` and structurally satisfy the ``Language`` Protocol.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_index.config import CodeIndexConfig
from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds
from code_index.languages import (
    Language,
    LanguageRegistry,
    active_plugins,
    load_extra_language,
)

FIXTURES = Path(__file__).parent / "fixtures" / "languages"
SYNTHETIC_PATH = FIXTURES / "extra" / "synthetic_lang.py"


@pytest.mark.parametrize(
    ("ext", "expected_name"),
    [
        (".py", "python"),
        (".cs", "csharp"),
        (".js", "javascript"),
        (".ts", "typescript"),
        (".go", "go"),
        (".fs", "fsharp"),
        (".fsi", "fsharp"),
        (".fsx", "fsharp"),
        (".lsl", "lsl"),
    ],
)
def test_builtin_registry_resolves_every_extension(ext: str, expected_name: str) -> None:
    registry = LanguageRegistry.from_builtins()
    plugin = registry.for_extension(ext)
    assert plugin is not None
    assert plugin.name == expected_name


def test_unknown_extension_returns_none() -> None:
    registry = LanguageRegistry.from_builtins()
    assert registry.for_extension(".xyz") is None


def test_runtime_checkable() -> None:
    registry = LanguageRegistry.from_builtins()
    # Recover one plugin instance per built-in via a public extension lookup
    # and confirm it passes `isinstance(..., Language)` — exercising the
    # `@runtime_checkable` Protocol contract on every shipped plugin.
    name_to_ext = {
        "python": ".py",
        "csharp": ".cs",
        "javascript": ".js",
        "typescript": ".ts",
        "go": ".go",
        "fsharp": ".fs",
        "lsl": ".lsl",
    }
    for name, ext in name_to_ext.items():
        plugin = registry.for_extension(ext)
        assert plugin is not None
        assert plugin.name == name
        assert isinstance(plugin, Language)


def test_load_extra_language_returns_list() -> None:
    plugins = load_extra_language(SYNTHETIC_PATH)
    assert len(plugins) == 1
    assert plugins[0].name == "synthetic"
    assert plugins[0].extensions == (".syn",)


def test_with_extras_adds_extension() -> None:
    registry = LanguageRegistry.from_builtins().with_extras([SYNTHETIC_PATH])
    plugin = registry.for_extension(".syn")
    assert plugin is not None
    assert plugin.name == "synthetic"


def test_filter_active_keeps_listed_drops_others() -> None:
    registry = LanguageRegistry.from_builtins().filter_active(["python", "go"])
    py = registry.for_extension(".py")
    assert py is not None
    assert py.name == "python"
    assert registry.for_extension(".cs") is None


def test_filter_active_none_passes_through() -> None:
    registry = LanguageRegistry.from_builtins().filter_active(None)
    for ext in (".py", ".cs", ".js", ".ts", ".go", ".fs", ".lsl"):
        assert registry.for_extension(ext) is not None


def test_load_extra_language_missing_file() -> None:
    with pytest.raises(CodeIndexError) as exc_info:
        load_extra_language(Path("/nonexistent/path.py"))
    assert exc_info.value.code == EXIT_CONFIG
    assert exc_info.value.kind == Kinds.CONFIG_BAD_PATH


def test_load_extra_language_missing_export(tmp_path: Path) -> None:
    target = tmp_path / "no_export.py"
    target.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(CodeIndexError) as exc_info:
        load_extra_language(target)
    assert exc_info.value.code == EXIT_CONFIG
    assert exc_info.value.kind == Kinds.CONFIG_UNKNOWN_LANGUAGE


def test_load_extra_language_languages_tuple(tmp_path: Path) -> None:
    target = tmp_path / "multi_lang.py"
    target.write_text(
        "from pathlib import Path\n"
        "from code_index.languages import Chunk, Edge, Symbol\n"
        "\n"
        "class A:\n"
        "    name = 'one'\n"
        "    extensions = ('.one',)\n"
        "    def chunk(self, path, content): return []\n"
        "    def symbols(self, path, content): return []\n"
        "    def imports(self, path, content): return []\n"
        "\n"
        "class B:\n"
        "    name = 'two'\n"
        "    extensions = ('.two',)\n"
        "    def chunk(self, path, content): return []\n"
        "    def symbols(self, path, content): return []\n"
        "    def imports(self, path, content): return []\n"
        "\n"
        "LANGUAGES = (A(), B())\n",
        encoding="utf-8",
    )
    plugins = load_extra_language(target)
    names = sorted(p.name for p in plugins)
    assert names == ["one", "two"]


def test_active_plugins_end_to_end() -> None:
    # The fixture config carries `languages = ["synthetic"]` and lists the
    # synthetic plugin under `extra_languages`. Phase 1's config loader uses
    # an approximation (file stem) for the language-name check that would
    # reject this combination, so we build the resolved CodeIndexConfig
    # directly — the architecture path the indexer will eventually use.
    config = CodeIndexConfig(
        version=">=0.1,<1.0",
        project="extra-demo",
        roots=["."],
        ignores=[],
        languages=["synthetic"],
        extra_languages=[str(SYNTHETIC_PATH)],
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=32,
    )
    registry = active_plugins(config)
    syn = registry.for_extension(".syn")
    assert syn is not None
    assert syn.name == "synthetic"
    assert registry.names() == ["synthetic"]
