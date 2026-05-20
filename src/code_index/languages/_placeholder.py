"""Placeholder plugin shape shared by step 001's seven plugin module stubs.

This module is private to the ``code_index.languages`` package. Steps 002-008
replace each plugin module's ``LANGUAGE = PlaceholderPlugin(...)`` line with a
real plugin instance and delete the import. Once the last plugin module is
replaced this file can be deleted.
"""

from __future__ import annotations

from pathlib import Path

from .protocol import Chunk, Edge, Symbol


class PlaceholderPlugin:
    """No-op plugin carrying only ``name`` and ``extensions``.

    Satisfies the ``Language`` Protocol structurally so the registry can
    dispatch by extension even before steps 002-008 land real parsing logic.
    """

    def __init__(self, name: str, extensions: tuple[str, ...]) -> None:
        self.name = name
        self.extensions = extensions

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        return []
