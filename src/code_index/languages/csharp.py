"""C# language plugin — tree-sitter via ``tree-sitter-language-pack``.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``. Chunks are emitted for every
``class`` / ``struct`` / ``record`` / ``interface`` / ``enum`` declaration,
every method / constructor / local function, and one ``module``-kind chunk
collapsing any top-level statements at file scope (file-scoped programs).
Symbols are dotted ``Namespace.Type.Member`` names with generic type
parameters stripped. Imports come from ``using`` directives — aliases and
``static`` / ``global`` qualifiers are dropped from the edge target.

Parsing is tolerant: tree-sitter recovers from many errors, and any unexpected
exception during parsing or traversal collapses to an empty result list.
Phase 4 wraps plugin calls and decides whether to log per skip-or-strict.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tree_sitter_language_pack import Node, get_parser

from .protocol import Chunk, Edge, Symbol

# A single parser is reused across calls — instantiation cost is non-trivial
# and the underlying object is safe to reuse for repeated ``parse`` calls.
_PARSER = get_parser("csharp")

_TYPE_NODES = {
    "class_declaration": "class",
    "struct_declaration": "struct",
    "record_declaration": "record",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
}

_FUNCTION_NODES = {
    "method_declaration",
    "constructor_declaration",
    "local_function_statement",
}


def _parse(content: str) -> Node | None:
    try:
        tree = _PARSER.parse(content)
    except Exception:
        return None
    if tree is None:
        return None
    try:
        return tree.root_node()
    except Exception:
        return None


def _node_text(node: Node, content_bytes: bytes) -> str:
    return content_bytes[node.start_byte() : node.end_byte()].decode("utf-8", errors="replace")


def _name_text(node: Node, content_bytes: bytes) -> str | None:
    """Return the bare ``name`` field of ``node`` as text, or ``None``."""
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, content_bytes)


def _join_scope(stack: tuple[str, ...]) -> str | None:
    return ".".join(stack) if stack else None


def _slice_lines(content: str, start: int, end: int) -> str:
    """Return the inclusive 1-based line range ``[start, end]`` from ``content``."""
    lines = content.splitlines(keepends=True)
    return "".join(lines[start - 1 : end])


def _chunk_kind(node: Node) -> str | None:
    kind = node.kind()
    if kind in _TYPE_NODES:
        return _TYPE_NODES[kind]
    if kind in _FUNCTION_NODES:
        return "function"
    return None


def _iter_named_children(node: Node) -> Iterator[Node]:
    for i in range(node.named_child_count()):
        child = node.named_child(i)
        if child is not None:
            yield child


def _walk_namespace_name(node: Node, content_bytes: bytes) -> str:
    """Flatten ``identifier`` / ``qualified_name`` nodes back into a dotted string."""
    if node.kind() == "identifier":
        return _node_text(node, content_bytes)
    # qualified_name has ``qualifier`` and ``name`` fields.
    qualifier = node.child_by_field_name("qualifier")
    name = node.child_by_field_name("name")
    if qualifier is not None and name is not None:
        return f"{_walk_namespace_name(qualifier, content_bytes)}.{_node_text(name, content_bytes)}"
    # Fallback: raw text (handles unexpected shapes without raising).
    return _node_text(node, content_bytes).strip()


def _collect(
    node: Node,
    scope: tuple[str, ...],
    content_bytes: bytes,
    out: list[tuple[Node, tuple[str, ...], str, str | None]],
) -> None:
    """Pre-order walk: append ``(node, scope, kind, name)`` for every chunkable node.

    Recurses through namespaces (which adjust scope but are not themselves
    chunked) and through the bodies of types and functions so nested members
    surface with their dotted scope.
    """
    kind = node.kind()

    if kind == "namespace_declaration":
        name_node = node.child_by_field_name("name")
        ns_name = _walk_namespace_name(name_node, content_bytes) if name_node is not None else ""
        if ns_name:
            inner_scope = scope + tuple(part for part in ns_name.split(".") if part)
        else:
            inner_scope = scope
        body = node.child_by_field_name("body")
        if body is not None:
            for child in _iter_named_children(body):
                _collect(child, inner_scope, content_bytes, out)
        return

    chunk_kind = _chunk_kind(node)
    if chunk_kind is None:
        # Recurse into children that may contain nested declarations (e.g. an
        # unrecognized wrapper node) without emitting a chunk for the wrapper
        # itself.
        for child in _iter_named_children(node):
            _collect(child, scope, content_bytes, out)
        return

    name = _name_text(node, content_bytes)
    out.append((node, scope, chunk_kind, name))

    inner_scope = scope + (name,) if name is not None else scope

    if chunk_kind in {"class", "struct", "record", "interface", "enum"}:
        body = node.child_by_field_name("body")
        if body is not None:
            for child in _iter_named_children(body):
                _collect(child, inner_scope, content_bytes, out)
        return

    # Function-like node: descend into its body for nested local functions.
    body = node.child_by_field_name("body")
    if body is not None:
        for child in _iter_named_children(body):
            _collect(child, inner_scope, content_bytes, out)


def _toplevel_statement_range(root: Node) -> tuple[int, int] | None:
    """Return the inclusive 1-based line range covering all ``global_statement`` children."""
    first: Node | None = None
    last: Node | None = None
    for child in _iter_named_children(root):
        if child.kind() == "global_statement":
            if first is None:
                first = child
            last = child
    if first is None or last is None:
        return None
    return (first.start_position().row + 1, last.end_position().row + 1)


class CSharpPlugin:
    """Tree-sitter-backed plugin for ``.cs`` source."""

    name = "csharp"
    extensions = (".cs",)

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            chunks: list[Chunk] = []

            tl = _toplevel_statement_range(root)
            if tl is not None:
                start, end = tl
                chunks.append(
                    Chunk(
                        start_line=start,
                        end_line=end,
                        kind="module",
                        name=None,
                        scope=None,
                        text=_slice_lines(content, start, end),
                    )
                )

            collected: list[tuple[Node, tuple[str, ...], str, str | None]] = []
            for child in _iter_named_children(root):
                _collect(child, (), content_bytes, collected)

            for node, scope_stack, chunk_kind, name in collected:
                start = node.start_position().row + 1
                end = node.end_position().row + 1
                chunks.append(
                    Chunk(
                        start_line=start,
                        end_line=end,
                        kind=chunk_kind,
                        name=name,
                        scope=_join_scope(scope_stack),
                        text=_slice_lines(content, start, end),
                    )
                )

            return chunks
        except Exception:
            return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            collected: list[tuple[Node, tuple[str, ...], str, str | None]] = []
            for child in _iter_named_children(root):
                _collect(child, (), content_bytes, collected)

            symbols: list[Symbol] = []
            for node, scope_stack, _chunk_kind, name in collected:
                if name is None:
                    continue
                dotted = ".".join(scope_stack + (name,))
                line = node.start_position().row + 1
                symbols.append(Symbol(name=dotted, kind="def", line=line))
            return symbols
        except Exception:
            return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            edges: list[Edge] = []
            for child in _iter_named_children(root):
                if child.kind() != "using_directive":
                    continue
                target_node = _using_target(child)
                if target_node is None:
                    continue
                target = _walk_namespace_name(target_node, content_bytes)
                if not target:
                    continue
                line = child.start_position().row + 1
                edges.append(Edge(target=target, kind="import", line=line, meta=None))
            return edges
        except Exception:
            return []


def _using_target(directive: Node) -> Node | None:
    """Pick the target node out of a ``using_directive``.

    Forms handled:

    * ``using System;`` — one named child (the identifier or qualified_name).
    * ``using static System.Math;`` — same; ``static`` is an anonymous token.
    * ``using X = System.IO.Path;`` — the ``name`` field carries the alias
      identifier; the target is the OTHER named child.
    * ``global using System;`` — same as plain ``using``.
    """
    alias = directive.child_by_field_name("name")
    alias_range: tuple[int, int] | None = None
    if alias is not None:
        alias_range = (alias.start_byte(), alias.end_byte())
    target: Node | None = None
    for child in _iter_named_children(directive):
        if alias_range is not None and (child.start_byte(), child.end_byte()) == alias_range:
            continue
        if child.kind() in {"identifier", "qualified_name"}:
            target = child
    return target


LANGUAGE = CSharpPlugin()
