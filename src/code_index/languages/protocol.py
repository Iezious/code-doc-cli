"""Shared dataclasses and Protocol for language plugins.

Pinned per ``docs/architecture/chunking-and-languages.md`` "Plugin interface"
section. Each plugin returns lists of these frozen dataclasses from its
``chunk`` / ``symbols`` / ``imports`` methods. The ``Language`` Protocol is
``@runtime_checkable`` so the registry can verify built-in and extra plugins
structurally without forcing inheritance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Chunk:
    """One indexable region of source: a function body, type decl, module, etc.

    Fields mirror the design doc:

    * ``start_line`` / ``end_line`` — 1-based inclusive line range.
    * ``kind`` — language-agnostic category, e.g. ``"function"``, ``"type"``,
      ``"module"``, ``"class"``, ``"state"``, ``"event"``.
    * ``name`` — declared name when present, else ``None`` (e.g. a module-level
      block with no enclosing decl).
    * ``scope`` — dotted enclosing scope, e.g. ``"MyModule.SubModule"`` or
      ``"default"`` for an LSL state. ``None`` when the chunk has no
      meaningful enclosing scope.
    * ``text`` — the raw source slice. The walker (Phase 4) is responsible
      for any normalization.
    """

    start_line: int
    end_line: int
    kind: str
    name: str | None
    scope: str | None
    text: str


@dataclass(frozen=True)
class Symbol:
    """One identifier occurrence — a definition or a reference.

    ``kind`` is ``"def"`` for declarations and ``"ref"`` for usages. ``line``
    is 1-based. Plugins emit definitions for every named declaration they can
    chunk; references are language-dependent (e.g. call sites for the LSL
    plugin).
    """

    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class Edge:
    """A directed relationship to an identifier or external resource.

    Used for imports, calls, listens, link messages, HTTP requests, and any
    other plugin-specific outbound edge. ``target`` is a symbol name or
    external identifier (URL, channel, module path). ``meta`` carries
    language-specific extras; ``None`` when not needed.
    """

    target: str
    kind: str
    line: int
    meta: dict[str, object] | None


@runtime_checkable
class Language(Protocol):
    """Structural contract every plugin must satisfy.

    A plugin is any object exposing ``name`` (string), ``extensions`` (tuple
    of extension strings including the leading dot), and the three pure
    methods. Plugins must not perform I/O: callers pass both the path and the
    already-read content.
    """

    name: str
    extensions: tuple[str, ...]

    def chunk(self, path: Path, content: str) -> list[Chunk]: ...
    def symbols(self, path: Path, content: str) -> list[Symbol]: ...
    def imports(self, path: Path, content: str) -> list[Edge]: ...
