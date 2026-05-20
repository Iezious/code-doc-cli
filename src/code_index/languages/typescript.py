"""TypeScript language plugin — tree-sitter via ``tree-sitter-language-pack``.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``. Behaviour is a strict superset
of the JavaScript plugin: every chunk / symbol / edge form the JS plugin emits
is emitted here too, with these additions:

* Extra chunk kinds — ``"interface"``, ``"type"`` (for ``type`` aliases),
  ``"enum"``, and ``"namespace"`` (TS internal modules).
* Namespace nesting — declarations inside a ``namespace`` block carry the
  namespace name as their dotted ``scope``, mirroring how the C# plugin treats
  ``namespace`` blocks.
* Generic type parameters are stripped from ``name`` (the grammar's ``name``
  field is the bare identifier; the ``type_parameters`` field is a sibling).
* Type-only imports — ``import type { ... } from "..."`` carries
  ``meta["type_only"] = True``. Per-specifier type-only (``import { type X, Y }
  from "..."``) is NOT disambiguated in Phase 3: the edge omits ``type_only``
  and lists every binding under ``meta["names"]`` regardless of per-specifier
  ``type`` keywords. See ``005.context.md``.

Two grammars are used — ``tree-sitter-language-pack`` ships separate
``typescript`` and ``tsx`` parsers. Dispatch is by file extension at parse
time: ``.tsx`` → ``tsx`` grammar, ``.ts`` (and any other accepted extension)
→ ``typescript`` grammar.

Parsing is tolerant: tree-sitter recovers from many errors, and any unexpected
exception during parsing or traversal collapses to an empty result list.
Phase 4 wraps plugin calls and decides whether to log per skip-or-strict.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tree_sitter_language_pack import Node, get_parser

from .protocol import Chunk, Edge, Symbol

# One parser per grammar, reused across calls.
_PARSER_TS = get_parser("typescript")
_PARSER_TSX = get_parser("tsx")


def _parse(path: Path, content: str) -> Node | None:
    parser = _PARSER_TSX if path.suffix.lower() == ".tsx" else _PARSER_TS
    try:
        tree = parser.parse(content)
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
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, content_bytes)


def _slice_lines(content: str, start: int, end: int) -> str:
    """Return the inclusive 1-based line range ``[start, end]`` from ``content``."""
    lines = content.splitlines(keepends=True)
    return "".join(lines[start - 1 : end])


def _iter_named_children(node: Node) -> Iterator[Node]:
    for i in range(node.named_child_count()):
        child = node.named_child(i)
        if child is not None:
            yield child


def _iter_children(node: Node) -> Iterator[Node]:
    for i in range(node.child_count()):
        child = node.child(i)
        if child is not None:
            yield child


def _has_default_keyword(node: Node) -> Node | None:
    """Return the ``default`` keyword node inside an ``export_statement``, or ``None``."""
    for child in _iter_children(node):
        if not child.is_named() and child.kind() == "default":
            return child
    return None


def _has_type_keyword(node: Node) -> bool:
    """Return ``True`` if ``import_statement`` has a top-level ``type`` keyword.

    The TS grammar marks ``import type { ... } from "..."`` by inserting an
    unnamed ``type`` token between ``import`` and the import clause. Returning
    ``True`` here means the whole statement is type-only. Per-specifier
    ``type`` keywords (``import { type X, Y } from "..."``) live inside
    ``import_specifier`` nodes and are intentionally ignored — see module
    docstring.
    """
    return any(
        not child.is_named() and child.kind() == "type"
        for child in _iter_children(node)
    )


def _arrow_init(declarator: Node) -> Node | None:
    """Return the ``arrow_function`` initializer of ``declarator``, or ``None``."""
    value = declarator.child_by_field_name("value")
    if value is not None and value.kind() == "arrow_function":
        return value
    return None


def _require_target(call: Node, content_bytes: bytes) -> str | None:
    """Return the string argument of a ``require(...)`` call, or ``None``."""
    if call.kind() != "call_expression":
        return None
    callee = call.child_by_field_name("function")
    if callee is None or callee.kind() != "identifier":
        return None
    if _node_text(callee, content_bytes) != "require":
        return None
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    named = list(_iter_named_children(args))
    if len(named) != 1 or named[0].kind() != "string":
        return None
    return _string_value(named[0], content_bytes)


def _string_value(string_node: Node, content_bytes: bytes) -> str:
    """Return the inner text of a tree-sitter ``string`` node (quotes stripped)."""
    for child in _iter_named_children(string_node):
        if child.kind() == "string_fragment":
            return _node_text(child, content_bytes)
    return ""


def _lexical_declarators(node: Node) -> Iterator[Node]:
    if node.kind() not in {"lexical_declaration", "variable_declaration"}:
        return
    for child in _iter_named_children(node):
        if child.kind() == "variable_declarator":
            yield child


def _declarator_require_call(declarator: Node) -> Node | None:
    value = declarator.child_by_field_name("value")
    if value is not None and value.kind() == "call_expression":
        return value
    return None


def _expression_call(stmt: Node) -> Node | None:
    if stmt.kind() != "expression_statement":
        return None
    for child in _iter_named_children(stmt):
        if child.kind() == "call_expression":
            return child
    return None


def _internal_module(stmt: Node) -> Node | None:
    """If ``stmt`` is a top-level form wrapping ``internal_module``, return it.

    Top-level ``namespace Foo {}`` parses as ``expression_statement ->
    internal_module``; ``export namespace Foo {}`` parses as ``export_statement
    -> internal_module`` via the ``declaration`` field. Both are recognised.
    """
    if stmt.kind() == "expression_statement":
        for child in _iter_named_children(stmt):
            if child.kind() == "internal_module":
                return child
        return None
    if stmt.kind() == "export_statement":
        decl = stmt.child_by_field_name("declaration")
        if decl is not None and decl.kind() == "internal_module":
            return decl
    return None


# ---------------------------------------------------------------------------
# Chunk extraction
# ---------------------------------------------------------------------------


def _emit_function_chunk(
    func_node: Node,
    name: str | None,
    scope: str | None,
    content: str,
    chunks: list[Chunk],
    span_node: Node | None = None,
) -> None:
    span = span_node if span_node is not None else func_node
    start = span.start_position().row + 1
    end = span.end_position().row + 1
    chunks.append(
        Chunk(
            start_line=start,
            end_line=end,
            kind="function",
            name=name,
            scope=scope,
            text=_slice_lines(content, start, end),
        )
    )


def _emit_class_chunk(
    class_node: Node,
    name: str | None,
    scope: str | None,
    content: str,
    content_bytes: bytes,
    chunks: list[Chunk],
    span_node: Node | None = None,
) -> None:
    """Append a ``class`` chunk and recurse into its body for method chunks."""
    span = span_node if span_node is not None else class_node
    start = span.start_position().row + 1
    end = span.end_position().row + 1
    chunks.append(
        Chunk(
            start_line=start,
            end_line=end,
            kind="class",
            name=name,
            scope=scope,
            text=_slice_lines(content, start, end),
        )
    )
    body = class_node.child_by_field_name("body")
    if body is None:
        return
    inner_scope_parts: tuple[str, ...]
    if scope and name is not None:
        inner_scope_parts = (scope, name)
        inner_scope: str | None = ".".join(inner_scope_parts)
    elif name is not None:
        inner_scope = name
    else:
        inner_scope = scope
    for child in _iter_named_children(body):
        if child.kind() != "method_definition":
            continue
        method_name = _name_text(child, content_bytes)
        m_start = child.start_position().row + 1
        m_end = child.end_position().row + 1
        chunks.append(
            Chunk(
                start_line=m_start,
                end_line=m_end,
                kind="function",
                name=method_name,
                scope=inner_scope,
                text=_slice_lines(content, m_start, m_end),
            )
        )


def _emit_typescript_decl_chunk(
    decl: Node,
    scope: str | None,
    content: str,
    content_bytes: bytes,
    chunks: list[Chunk],
    span_node: Node | None = None,
) -> None:
    """Append a chunk for a TS-only declaration: interface / type / enum."""
    kind_map = {
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    }
    chunk_kind = kind_map.get(decl.kind())
    if chunk_kind is None:
        return
    span = span_node if span_node is not None else decl
    start = span.start_position().row + 1
    end = span.end_position().row + 1
    chunks.append(
        Chunk(
            start_line=start,
            end_line=end,
            kind=chunk_kind,
            name=_name_text(decl, content_bytes),
            scope=scope,
            text=_slice_lines(content, start, end),
        )
    )


def _consume_for_chunk(
    stmt: Node,
    scope: str | None,
    content: str,
    content_bytes: bytes,
    chunks: list[Chunk],
) -> bool:
    """Try to emit a chunk for ``stmt`` under ``scope``; return ``True`` if consumed.

    Mirrors the JS plugin's contract: a ``True`` return means ``stmt``
    contributed at least one declaration chunk and should not be folded into
    a surrounding ``module`` chunk. TS extensions (interface / type / enum /
    namespace) are recognised in addition to the JS forms.
    """
    kind = stmt.kind()

    if kind == "function_declaration":
        name = _name_text(stmt, content_bytes)
        _emit_function_chunk(stmt, name, scope, content, chunks)
        return True

    if kind == "class_declaration":
        name = _name_text(stmt, content_bytes)
        _emit_class_chunk(stmt, name, scope, content, content_bytes, chunks)
        return True

    if kind in {"interface_declaration", "type_alias_declaration", "enum_declaration"}:
        _emit_typescript_decl_chunk(stmt, scope, content, content_bytes, chunks)
        return True

    if kind in {"lexical_declaration", "variable_declaration"}:
        declarators = list(_lexical_declarators(stmt))
        if not declarators:
            return False
        consumed_all = True
        emitted: list[tuple[Node, str | None]] = []
        for decl in declarators:
            arrow = _arrow_init(decl)
            if arrow is not None:
                name = _name_text(decl, content_bytes)
                emitted.append((arrow, name))
                continue
            require_call = _declarator_require_call(decl)
            if require_call is not None and _require_target(require_call, content_bytes) is not None:
                continue
            consumed_all = False
            break
        if not consumed_all:
            return False
        for arrow, name in emitted:
            _emit_function_chunk(arrow, name, scope, content, chunks, span_node=stmt)
        return True

    if kind == "expression_statement":
        # Top-level ``namespace Foo {}`` lives inside expression_statement.
        ns = _internal_module(stmt)
        if ns is not None:
            _emit_namespace_chunk(ns, scope, content, content_bytes, chunks, span_node=stmt)
            return True
        return False

    if kind == "export_statement":
        declaration = stmt.child_by_field_name("declaration")
        if declaration is not None:
            dkind = declaration.kind()
            if dkind == "function_declaration":
                name = _name_text(declaration, content_bytes)
                _emit_function_chunk(declaration, name, scope, content, chunks, span_node=stmt)
                return True
            if dkind == "class_declaration":
                name = _name_text(declaration, content_bytes)
                _emit_class_chunk(declaration, name, scope, content, content_bytes, chunks, span_node=stmt)
                return True
            if dkind in {"interface_declaration", "type_alias_declaration", "enum_declaration"}:
                _emit_typescript_decl_chunk(declaration, scope, content, content_bytes, chunks, span_node=stmt)
                return True
            if dkind == "internal_module":
                _emit_namespace_chunk(declaration, scope, content, content_bytes, chunks, span_node=stmt)
                return True
            if dkind in {"lexical_declaration", "variable_declaration"}:
                declarators = list(_lexical_declarators(declaration))
                arrows = [
                    (_arrow_init(d), _name_text(d, content_bytes))
                    for d in declarators
                ]
                if arrows and all(a is not None for a, _ in arrows):
                    for arrow, name in arrows:
                        assert arrow is not None
                        _emit_function_chunk(arrow, name, scope, content, chunks, span_node=stmt)
                    return True
                return False
            return False

        value = stmt.child_by_field_name("value")
        if value is not None:
            if value.kind() == "arrow_function":
                _emit_function_chunk(value, None, scope, content, chunks, span_node=stmt)
                return True
            if value.kind() == "function_expression":
                name = _name_text(value, content_bytes)
                _emit_function_chunk(value, name, scope, content, chunks, span_node=stmt)
                return True
            if value.kind() == "class":
                _emit_class_chunk(value, None, scope, content, content_bytes, chunks, span_node=stmt)
                return True
            return False

        return False

    return False


def _emit_namespace_chunk(
    ns_node: Node,
    scope: str | None,
    content: str,
    content_bytes: bytes,
    chunks: list[Chunk],
    span_node: Node | None = None,
) -> None:
    """Append a ``namespace`` chunk and recurse into its body."""
    name = _name_text(ns_node, content_bytes)
    span = span_node if span_node is not None else ns_node
    start = span.start_position().row + 1
    end = span.end_position().row + 1
    chunks.append(
        Chunk(
            start_line=start,
            end_line=end,
            kind="namespace",
            name=name,
            scope=scope,
            text=_slice_lines(content, start, end),
        )
    )

    inner_scope_parts = tuple(part for part in [scope, name] if part)
    inner_scope = ".".join(inner_scope_parts) if inner_scope_parts else None
    body = ns_node.child_by_field_name("body")
    if body is None:
        return
    for child in _iter_named_children(body):
        _consume_for_chunk(child, inner_scope, content, content_bytes, chunks)


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


_TS_EXPORT_DECL_KINDS = {
    "function_declaration",
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "type_alias_declaration",
}


def _emit_export_symbols(
    stmt: Node,
    scope: tuple[str, ...],
    stem: str,
    content_bytes: bytes,
    symbols: list[Symbol],
) -> None:
    """Append symbols for one ``export_statement``.

    ``scope`` is the dotted namespace path the export sits inside (empty tuple
    at file scope); it is joined onto the resulting symbol name with ``.``.
    """
    default_kw = _has_default_keyword(stmt)
    if default_kw is not None:
        symbols.append(
            Symbol(
                name=f"default::{stem}",
                kind="def",
                line=default_kw.start_position().row + 1,
            )
        )
        return

    declaration = stmt.child_by_field_name("declaration")
    if declaration is not None:
        dkind = declaration.kind()
        if dkind in _TS_EXPORT_DECL_KINDS:
            name_node = declaration.child_by_field_name("name")
            if name_node is not None:
                bare = _node_text(name_node, content_bytes)
                dotted = ".".join(scope + (bare,))
                symbols.append(
                    Symbol(
                        name=dotted,
                        kind="def",
                        line=name_node.start_position().row + 1,
                    )
                )
            return
        if dkind == "internal_module":
            _emit_namespace_symbols(declaration, scope, stem, content_bytes, symbols)
            return
        if dkind in {"lexical_declaration", "variable_declaration"}:
            for decl in _lexical_declarators(declaration):
                name_node = decl.child_by_field_name("name")
                if name_node is None or name_node.kind() != "identifier":
                    continue
                bare = _node_text(name_node, content_bytes)
                dotted = ".".join(scope + (bare,))
                symbols.append(
                    Symbol(
                        name=dotted,
                        kind="def",
                        line=name_node.start_position().row + 1,
                    )
                )
            return
        return

    # ``export { a, b }`` / ``export { a as b }`` — no declaration field.
    for child in _iter_named_children(stmt):
        if child.kind() != "export_clause":
            continue
        for spec in _iter_named_children(child):
            if spec.kind() != "export_specifier":
                continue
            alias = spec.child_by_field_name("alias")
            chosen = alias if alias is not None else spec.child_by_field_name("name")
            if chosen is None:
                continue
            bare = _node_text(chosen, content_bytes)
            dotted = ".".join(scope + (bare,))
            symbols.append(
                Symbol(
                    name=dotted,
                    kind="def",
                    line=chosen.start_position().row + 1,
                )
            )


def _emit_namespace_symbols(
    ns_node: Node,
    scope: tuple[str, ...],
    stem: str,
    content_bytes: bytes,
    symbols: list[Symbol],
) -> None:
    """Emit a symbol for ``ns_node`` itself plus any exports inside its body."""
    name_node = ns_node.child_by_field_name("name")
    if name_node is None:
        return
    bare = _node_text(name_node, content_bytes)
    dotted = ".".join(scope + (bare,))
    symbols.append(
        Symbol(
            name=dotted,
            kind="def",
            line=name_node.start_position().row + 1,
        )
    )
    body = ns_node.child_by_field_name("body")
    if body is None:
        return
    inner_scope = scope + (bare,)
    for child in _iter_named_children(body):
        if child.kind() == "export_statement":
            _emit_export_symbols(child, inner_scope, stem, content_bytes, symbols)


# ---------------------------------------------------------------------------
# Import / require extraction
# ---------------------------------------------------------------------------


def _import_clause_names(
    clause: Node,
    content_bytes: bytes,
) -> list[str]:
    """Return the imported binding names for an ``import_clause``.

    Per-specifier ``type`` keywords are intentionally ignored — the name
    listed is the bare identifier regardless of whether the specifier carries
    a leading ``type`` token. See module docstring for the rationale.
    """
    names: list[str] = []
    for child in _iter_named_children(clause):
        kind = child.kind()
        if kind == "identifier":
            names.append(_node_text(child, content_bytes))
        elif kind == "namespace_import":
            alias_node: Node | None = None
            for sub in _iter_named_children(child):
                if sub.kind() == "identifier":
                    alias_node = sub
                    break
            if alias_node is not None:
                names.append(f"* as {_node_text(alias_node, content_bytes)}")
            else:
                names.append("*")
        elif kind == "named_imports":
            for spec in _iter_named_children(child):
                if spec.kind() != "import_specifier":
                    continue
                spec_name = spec.child_by_field_name("name")
                if spec_name is None:
                    continue
                names.append(_node_text(spec_name, content_bytes))
    return names


def _import_statement_edge(
    stmt: Node,
    content_bytes: bytes,
) -> Edge | None:
    """Build the ``import``-kind edge for an ``import_statement``."""
    source = stmt.child_by_field_name("source")
    if source is None or source.kind() != "string":
        return None
    target = _string_value(source, content_bytes)
    names: list[str] = []
    for child in _iter_named_children(stmt):
        if child.kind() == "import_clause":
            names = _import_clause_names(child, content_bytes)
            break
    meta: dict[str, object] = {"names": names}
    if _has_type_keyword(stmt):
        meta["type_only"] = True
    return Edge(
        target=target,
        kind="import",
        line=stmt.start_position().row + 1,
        meta=meta,
    )


def _require_edge_from_statement(
    stmt: Node,
    content_bytes: bytes,
) -> list[Edge]:
    edges: list[Edge] = []
    if stmt.kind() in {"lexical_declaration", "variable_declaration"}:
        for decl in _lexical_declarators(stmt):
            call = _declarator_require_call(decl)
            if call is None:
                continue
            target = _require_target(call, content_bytes)
            if target is None:
                continue
            edges.append(
                Edge(
                    target=target,
                    kind="import",
                    line=stmt.start_position().row + 1,
                    meta={"names": [], "form": "require"},
                )
            )
        return edges

    call = _expression_call(stmt)
    if call is not None:
        target = _require_target(call, content_bytes)
        if target is not None:
            edges.append(
                Edge(
                    target=target,
                    kind="import",
                    line=stmt.start_position().row + 1,
                    meta={"names": [], "form": "require"},
                )
            )
    return edges


# ---------------------------------------------------------------------------
# Module-chunk filtering
# ---------------------------------------------------------------------------


_NEVER_MODULE = {
    "import_statement",
    "export_statement",
    "function_declaration",
    "class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
}


def _is_pure_require_or_arrow_decl(stmt: Node, content_bytes: bytes) -> bool:
    if stmt.kind() not in {"lexical_declaration", "variable_declaration"}:
        return False
    declarators = list(_lexical_declarators(stmt))
    if not declarators:
        return False
    for decl in declarators:
        if _arrow_init(decl) is not None:
            continue
        call = _declarator_require_call(decl)
        if call is not None and _require_target(call, content_bytes) is not None:
            continue
        return False
    return True


def _is_bare_require_call(stmt: Node, content_bytes: bytes) -> bool:
    call = _expression_call(stmt)
    if call is None:
        return False
    return _require_target(call, content_bytes) is not None


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class TypeScriptPlugin:
    """Tree-sitter-backed plugin for ``.ts`` and ``.tsx`` source."""

    name = "typescript"
    extensions = (".ts", ".tsx")

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        root = _parse(path, content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            chunks: list[Chunk] = []

            module_spans: list[tuple[int, int]] = []
            for child in _iter_named_children(root):
                kind = child.kind()
                if kind in _NEVER_MODULE:
                    if kind == "export_statement":
                        consumed = _consume_for_chunk(child, None, content, content_bytes, chunks)
                        if not consumed:
                            module_spans.append(
                                (
                                    child.start_position().row + 1,
                                    child.end_position().row + 1,
                                )
                            )
                        continue
                    if kind in {
                        "function_declaration",
                        "class_declaration",
                        "interface_declaration",
                        "type_alias_declaration",
                        "enum_declaration",
                    }:
                        _consume_for_chunk(child, None, content, content_bytes, chunks)
                    # import_statement → ignored entirely for chunks.
                    continue

                # Top-level ``namespace Foo {}`` parses as an
                # expression_statement; recognise and consume it.
                if kind == "expression_statement" and _internal_module(child) is not None:
                    _consume_for_chunk(child, None, content, content_bytes, chunks)
                    continue

                if _is_pure_require_or_arrow_decl(child, content_bytes):
                    _consume_for_chunk(child, None, content, content_bytes, chunks)
                    continue

                if _is_bare_require_call(child, content_bytes):
                    continue

                module_spans.append(
                    (
                        child.start_position().row + 1,
                        child.end_position().row + 1,
                    )
                )

            if module_spans:
                start = module_spans[0][0]
                end = module_spans[-1][1]
                chunks.insert(
                    0,
                    Chunk(
                        start_line=start,
                        end_line=end,
                        kind="module",
                        name=None,
                        scope=None,
                        text=_slice_lines(content, start, end),
                    ),
                )

            chunks.sort(key=lambda c: (c.start_line, c.end_line))
            return chunks
        except Exception:
            return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        root = _parse(path, content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            stem = path.stem
            symbols: list[Symbol] = []
            for child in _iter_named_children(root):
                if child.kind() == "export_statement":
                    _emit_export_symbols(child, (), stem, content_bytes, symbols)
            return symbols
        except Exception:
            return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        root = _parse(path, content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            edges: list[Edge] = []
            for child in _iter_named_children(root):
                kind = child.kind()
                if kind == "import_statement":
                    edge = _import_statement_edge(child, content_bytes)
                    if edge is not None:
                        edges.append(edge)
                    continue
                edges.extend(_require_edge_from_statement(child, content_bytes))
            return edges
        except Exception:
            return []


LANGUAGE = TypeScriptPlugin()
