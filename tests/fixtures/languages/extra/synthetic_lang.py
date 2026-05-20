"""Synthetic extra-language plugin fixture for the registry tests.

Loaded by ``test_languages_registry.py`` via the production
``load_extra_language`` helper and via ``active_plugins`` from a fixture
config. The plugin returns empty lists for every callable; the registry
contract is what is under test, not the parsing behavior.
"""

from pathlib import Path

from code_index.languages import Chunk, Edge, Symbol


class SyntheticPlugin:
    name = "synthetic"
    extensions = (".syn",)

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        return []


LANGUAGE = SyntheticPlugin()
