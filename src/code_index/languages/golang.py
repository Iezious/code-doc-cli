"""Go language plugin — tree-sitter via ``tree-sitter-language-pack``.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``. Chunks are emitted for every
``function_declaration`` and ``method_declaration`` (kind ``"function"``),
every ``type_declaration`` covering structs, interfaces, and aliases
(kind ``"type"``), and for the ``package_clause`` plus every file-scope
``var_declaration`` / ``const_declaration`` (kind ``"module"`` — one chunk per
block, so a grouped ``var ( ... )`` collapses into a single chunk).

Symbols are package-qualified per the 2026-05-19 architecture clarification:
top-level identifiers become ``<pkg>.<Name>`` and methods become
``<pkg>.<ReceiverType>.<MethodName>``, with the method's chunk carrying
``scope = "<pkg>.<ReceiverType>"``. The receiver's pointer asterisk is
stripped for both ``scope`` and ``Symbol.name``. When a file lacks a
``package`` clause the prefix collapses to the empty string, so symbol names
fall back to the bare identifier — the snapshot pins this fallback.

Imports cover every entry in single ``import "fmt"`` declarations and every
spec in a grouped ``import ( ... )`` block; each spec is its own edge with
its own line. Aliases — including the blank import ``_`` and dot import
``.`` forms — are recorded in ``meta["alias"]``; absent aliases produce
``meta = None``.

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
_PARSER = get_parser("go")


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


def _slice_lines(content: str, start: int, end: int) -> str:
    """Return the inclusive 1-based line range ``[start, end]`` from ``content``."""
    lines = content.splitlines(keepends=True)
    return "".join(lines[start - 1 : end])


def _iter_named_children(node: Node) -> Iterator[Node]:
    for i in range(node.named_child_count()):
        child = node.named_child(i)
        if child is not None:
            yield child


def _name_text(node: Node, content_bytes: bytes) -> str | None:
    """Return the bare ``name`` field of ``node`` as text, or ``None``."""
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, content_bytes)


def _package_name(root: Node, content_bytes: bytes) -> str:
    """Return the declared package name, or the empty string if absent.

    ``package_clause`` does not expose a ``name`` field — the package
    identifier is its first (and only) named child. Returning ``""`` when no
    ``package`` clause is present lets the symbol-naming code fall back to
    bare identifiers without branching.
    """
    for child in _iter_named_children(root):
        if child.kind() != "package_clause":
            continue
        for sub in _iter_named_children(child):
            if sub.kind() == "package_identifier":
                return _node_text(sub, content_bytes)
    return ""


def _qualify(prefix: str, *parts: str) -> str:
    """Join ``prefix`` with one or more ``parts``, skipping empty pieces.

    Used to build ``Symbol.name`` and the method scope from the package
    prefix and one or two identifiers. Empty pieces are dropped so a missing
    package clause yields the bare dotted form (e.g. ``"Frobnicator.Run"``).
    """
    pieces = [p for p in (prefix, *parts) if p]
    return ".".join(pieces)


def _receiver_type(method: Node, content_bytes: bytes) -> str | None:
    """Extract the receiver type identifier for a ``method_declaration``.

    The receiver is a ``parameter_list`` containing one
    ``parameter_declaration`` whose ``type`` field is either a
    ``type_identifier`` (value receiver) or a ``pointer_type`` wrapping a
    ``type_identifier`` (pointer receiver). The pointer asterisk is stripped
    so ``(w *Widget)`` and ``(w Widget)`` both yield ``"Widget"``.
    """
    receiver = method.child_by_field_name("receiver")
    if receiver is None:
        return None
    for child in _iter_named_children(receiver):
        if child.kind() != "parameter_declaration":
            continue
        type_node = child.child_by_field_name("type")
        if type_node is None:
            continue
        if type_node.kind() == "pointer_type":
            for sub in _iter_named_children(type_node):
                if sub.kind() == "type_identifier":
                    return _node_text(sub, content_bytes)
            return None
        if type_node.kind() == "type_identifier":
            return _node_text(type_node, content_bytes)
    return None


def _type_decl_name(decl: Node, content_bytes: bytes) -> str | None:
    """Return the declared type name for a ``type_declaration``.

    A ``type_declaration`` wraps a single ``type_spec`` (``type Foo struct``,
    ``type Foo interface``) or a ``type_alias`` (``type Foo = ...``). Both
    expose ``name`` as a ``type_identifier`` field.
    """
    for child in _iter_named_children(decl):
        if child.kind() in {"type_spec", "type_alias"}:
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                return _node_text(name_node, content_bytes)
    return None


# ---------------------------------------------------------------------------
# Chunk extraction
# ---------------------------------------------------------------------------


def _emit_chunk(
    chunks: list[Chunk],
    node: Node,
    kind: str,
    name: str | None,
    scope: str | None,
    content: str,
) -> None:
    start = node.start_position().row + 1
    end = node.end_position().row + 1
    chunks.append(
        Chunk(
            start_line=start,
            end_line=end,
            kind=kind,
            name=name,
            scope=scope,
            text=_slice_lines(content, start, end),
        )
    )


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _import_spec_edges(
    spec: Node,
    content_bytes: bytes,
    edges: list[Edge],
) -> None:
    """Append one ``import``-kind edge for an ``import_spec``.

    The grammar exposes ``name`` (optional: ``package_identifier``,
    ``blank_identifier``, or ``dot``) and ``path`` (always an
    ``interpreted_string_literal``). The line is taken from the spec itself
    so each entry in a grouped block carries its own line.
    """
    path_node = spec.child_by_field_name("path")
    if path_node is None:
        return
    target = ""
    for sub in _iter_named_children(path_node):
        if sub.kind() == "interpreted_string_literal_content":
            target = _node_text(sub, content_bytes)
            break
    if not target:
        return

    alias: str | None = None
    name_node = spec.child_by_field_name("name")
    if name_node is not None:
        # ``name`` may be a package_identifier, ``_`` (blank_identifier), or
        # ``.`` (dot). The raw token is the alias.
        alias = _node_text(name_node, content_bytes)

    meta: dict[str, object] | None = {"alias": alias} if alias is not None else None
    edges.append(
        Edge(
            target=target,
            kind="import",
            line=spec.start_position().row + 1,
            meta=meta,
        )
    )


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class GoPlugin:
    """Tree-sitter-backed plugin for ``.go`` source."""

    name = "go"
    extensions = (".go",)

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            pkg = _package_name(root, content_bytes)
            chunks: list[Chunk] = []

            for child in _iter_named_children(root):
                kind = child.kind()
                if kind == "package_clause" or kind in {
                    "var_declaration",
                    "const_declaration",
                }:
                    _emit_chunk(chunks, child, "module", None, None, content)
                elif kind == "function_declaration":
                    name = _name_text(child, content_bytes)
                    _emit_chunk(chunks, child, "function", name, None, content)
                elif kind == "method_declaration":
                    name = _name_text(child, content_bytes)
                    receiver = _receiver_type(child, content_bytes)
                    scope = _qualify(pkg, receiver) if receiver else (pkg or None)
                    _emit_chunk(chunks, child, "function", name, scope or None, content)
                elif kind == "type_declaration":
                    name = _type_decl_name(child, content_bytes)
                    _emit_chunk(chunks, child, "type", name, None, content)

            return chunks
        except Exception:
            return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            pkg = _package_name(root, content_bytes)
            symbols: list[Symbol] = []

            for child in _iter_named_children(root):
                kind = child.kind()
                if kind == "function_declaration":
                    name = _name_text(child, content_bytes)
                    if name is None:
                        continue
                    line = child.start_position().row + 1
                    symbols.append(
                        Symbol(name=_qualify(pkg, name), kind="def", line=line)
                    )
                elif kind == "method_declaration":
                    name = _name_text(child, content_bytes)
                    if name is None:
                        continue
                    receiver = _receiver_type(child, content_bytes)
                    line = child.start_position().row + 1
                    if receiver:
                        symbols.append(
                            Symbol(
                                name=_qualify(pkg, receiver, name),
                                kind="def",
                                line=line,
                            )
                        )
                    else:
                        symbols.append(
                            Symbol(name=_qualify(pkg, name), kind="def", line=line)
                        )
                elif kind == "type_declaration":
                    name = _type_decl_name(child, content_bytes)
                    if name is None:
                        continue
                    # Use the inner ``type_spec`` / ``type_alias`` line so
                    # the symbol points at the identifier rather than the
                    # ``type`` keyword.
                    line = child.start_position().row + 1
                    symbols.append(
                        Symbol(name=_qualify(pkg, name), kind="def", line=line)
                    )

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
                if child.kind() != "import_declaration":
                    continue
                # An ``import_declaration`` either wraps a single ``import_spec``
                # (``import "fmt"``) or an ``import_spec_list`` containing
                # multiple specs (``import ( ... )``).
                for sub in _iter_named_children(child):
                    if sub.kind() == "import_spec":
                        _import_spec_edges(sub, content_bytes, edges)
                    elif sub.kind() == "import_spec_list":
                        for spec in _iter_named_children(sub):
                            if spec.kind() == "import_spec":
                                _import_spec_edges(spec, content_bytes, edges)

            return edges
        except Exception:
            return []


LANGUAGE = GoPlugin()
