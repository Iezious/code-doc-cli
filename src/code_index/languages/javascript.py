"""JavaScript language plugin — tree-sitter via ``tree-sitter-language-pack``.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``. Chunks are emitted for every
function / class declaration, every arrow function assigned at module scope,
every class method, and one ``module``-kind chunk collapsing any top-level
statements that are not consumed by an import, an export, a chunk-emitting
declaration, or a module-scope ``require()`` call.

Symbols carry only source-declared qualifiers per the 2026-05-19 architecture
clarification:

* Named exports use the export name verbatim (``export { a as b }`` emits a
  symbol named ``b``).
* Default exports collapse to the synthetic name ``default::<file-stem>``
  regardless of any inner identifier — the export name is ``default``.

Imports cover both ESM ``import`` statements (default, named, namespace, and
side-effect forms) and module-scope CommonJS ``require()`` calls. ``meta`` is
always a ``dict`` so consumers do not have to special-case the shape; the
``"form"`` field is present only for ``require`` edges.

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
_PARSER = get_parser("javascript")


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


def _arrow_init(declarator: Node) -> Node | None:
    """Return the ``arrow_function`` initializer of ``declarator``, or ``None``."""
    value = declarator.child_by_field_name("value")
    if value is not None and value.kind() == "arrow_function":
        return value
    return None


def _require_target(call: Node, content_bytes: bytes) -> str | None:
    """Return the string argument of a ``require(...)`` call, or ``None``.

    Accepts only the canonical shape: a single string argument. Returns the
    raw string contents (the value of the ``string_fragment`` child).
    """
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
    # Empty string literal: no string_fragment child.
    return ""


def _lexical_declarators(node: Node) -> Iterator[Node]:
    """Yield each ``variable_declarator`` inside a ``lexical_declaration`` /
    ``variable_declaration``."""
    if node.kind() not in {"lexical_declaration", "variable_declaration"}:
        return
    for child in _iter_named_children(node):
        if child.kind() == "variable_declarator":
            yield child


def _declarator_require_call(declarator: Node) -> Node | None:
    """If ``declarator``'s initializer is a ``require(...)`` call, return it."""
    value = declarator.child_by_field_name("value")
    if value is not None and value.kind() == "call_expression":
        return value
    return None


def _expression_call(stmt: Node) -> Node | None:
    """If ``stmt`` is an ``expression_statement`` wrapping a ``call_expression``,
    return that call; else ``None``."""
    if stmt.kind() != "expression_statement":
        return None
    for child in _iter_named_children(stmt):
        if child.kind() == "call_expression":
            return child
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
    """Append a ``function`` chunk for ``func_node`` (or ``span_node`` if given)."""
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
            scope=None,
            text=_slice_lines(content, start, end),
        )
    )
    body = class_node.child_by_field_name("body")
    if body is None:
        return
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
                scope=name,
                text=_slice_lines(content, m_start, m_end),
            )
        )


def _consume_for_chunk(
    stmt: Node,
    content: str,
    content_bytes: bytes,
    chunks: list[Chunk],
) -> bool:
    """Try to emit a chunk for a top-level ``stmt``; return ``True`` if consumed.

    ``True`` means the statement contributed a function / class chunk (or was
    an export wrapping one) and should not feed the ``module`` chunk. Imports
    and module-scope ``require`` lexical declarations are filtered separately
    and never reach this function with a positive result.
    """
    kind = stmt.kind()

    if kind == "function_declaration":
        name = _name_text(stmt, content_bytes)
        _emit_function_chunk(stmt, name, None, content, chunks)
        return True

    if kind == "class_declaration":
        name = _name_text(stmt, content_bytes)
        _emit_class_chunk(stmt, name, content, content_bytes, chunks)
        return True

    if kind in {"lexical_declaration", "variable_declaration"}:
        # All-or-nothing: a declaration whose every declarator is either an
        # arrow-function or a module-scope ``require`` is consumed; mixed
        # declarations fall through to the module chunk.
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
                # Module-scope require: consumed by imports(), excluded here.
                continue
            consumed_all = False
            break
        if not consumed_all:
            return False
        for arrow, name in emitted:
            _emit_function_chunk(arrow, name, None, content, chunks, span_node=stmt)
        return True

    if kind == "export_statement":
        declaration = stmt.child_by_field_name("declaration")
        if declaration is not None:
            dkind = declaration.kind()
            if dkind == "function_declaration":
                name = _name_text(declaration, content_bytes)
                _emit_function_chunk(declaration, name, None, content, chunks, span_node=stmt)
                return True
            if dkind == "class_declaration":
                name = _name_text(declaration, content_bytes)
                _emit_class_chunk(declaration, name, content, content_bytes, chunks, span_node=stmt)
                return True
            if dkind in {"lexical_declaration", "variable_declaration"}:
                # Recurse via the same arrow-vs-require logic, but exports
                # never carry require() initializers in well-formed code; if
                # one slips through, treat the whole export as non-chunkable.
                declarators = list(_lexical_declarators(declaration))
                arrows = [
                    (_arrow_init(d), _name_text(d, content_bytes))
                    for d in declarators
                ]
                if arrows and all(a is not None for a, _ in arrows):
                    for arrow, name in arrows:
                        assert arrow is not None
                        _emit_function_chunk(arrow, name, None, content, chunks, span_node=stmt)
                    return True
                return False
            return False

        value = stmt.child_by_field_name("value")
        if value is not None:
            if value.kind() == "arrow_function":
                _emit_function_chunk(value, None, None, content, chunks, span_node=stmt)
                return True
            if value.kind() == "function_expression":
                name = _name_text(value, content_bytes)
                _emit_function_chunk(value, name, None, content, chunks, span_node=stmt)
                return True
            if value.kind() == "class":
                # Anonymous class expression in `export default class { ... }`.
                _emit_class_chunk(value, None, content, content_bytes, chunks, span_node=stmt)
                return True
            return False

        # export { a, b }; export { a } from "mod"; — no chunk.
        return False

    return False


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


def _emit_export_symbols(
    stmt: Node,
    stem: str,
    content_bytes: bytes,
    symbols: list[Symbol],
) -> None:
    """Append symbols for one ``export_statement``."""
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
        if dkind == "function_declaration" or dkind == "class_declaration":
            name_node = declaration.child_by_field_name("name")
            if name_node is not None:
                symbols.append(
                    Symbol(
                        name=_node_text(name_node, content_bytes),
                        kind="def",
                        line=name_node.start_position().row + 1,
                    )
                )
            return
        if dkind in {"lexical_declaration", "variable_declaration"}:
            for decl in _lexical_declarators(declaration):
                name_node = decl.child_by_field_name("name")
                if name_node is None or name_node.kind() != "identifier":
                    continue
                symbols.append(
                    Symbol(
                        name=_node_text(name_node, content_bytes),
                        kind="def",
                        line=name_node.start_position().row + 1,
                    )
                )
            return
        return

    # Plain ``export { a, b }`` / ``export { a as b }`` form.
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
            symbols.append(
                Symbol(
                    name=_node_text(chosen, content_bytes),
                    kind="def",
                    line=chosen.start_position().row + 1,
                )
            )


# ---------------------------------------------------------------------------
# Import / require extraction
# ---------------------------------------------------------------------------


def _import_clause_names(
    clause: Node,
    content_bytes: bytes,
) -> list[str]:
    """Return the imported binding names for an ``import_clause``."""
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
    return Edge(
        target=target,
        kind="import",
        line=stmt.start_position().row + 1,
        meta={"names": names},
    )


def _require_edge_from_statement(
    stmt: Node,
    content_bytes: bytes,
) -> list[Edge]:
    """Pick out module-scope ``require`` calls from ``stmt``.

    Handles:

    * ``const x = require("mod");`` — any number of declarators.
    * ``require("mod");`` — bare call as an expression statement.
    """
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
}


def _is_pure_require_or_arrow_decl(stmt: Node, content_bytes: bytes) -> bool:
    """Return ``True`` if every declarator in ``stmt`` is an arrow or require call.

    Such declarations are consumed by either the chunk extractor (arrows) or
    the imports extractor (requires) and must be excluded from the module
    chunk to avoid duplicating their source text.
    """
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
    """Return ``True`` for ``require("mod");`` as a top-level expression."""
    call = _expression_call(stmt)
    if call is None:
        return False
    return _require_target(call, content_bytes) is not None


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class JavaScriptPlugin:
    """Tree-sitter-backed plugin for ``.js`` / ``.mjs`` / ``.cjs`` source."""

    name = "javascript"
    extensions = (".js", ".mjs", ".cjs")

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        root = _parse(content)
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
                        consumed = _consume_for_chunk(child, content, content_bytes, chunks)
                        if not consumed:
                            module_spans.append(
                                (
                                    child.start_position().row + 1,
                                    child.end_position().row + 1,
                                )
                            )
                        continue
                    if kind in {"function_declaration", "class_declaration"}:
                        _consume_for_chunk(child, content, content_bytes, chunks)
                    # import_statement → ignored entirely for chunks.
                    continue

                if _is_pure_require_or_arrow_decl(child, content_bytes):
                    _consume_for_chunk(child, content, content_bytes, chunks)
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
        root = _parse(content)
        if root is None:
            return []
        try:
            content_bytes = content.encode("utf-8")
            stem = path.stem
            symbols: list[Symbol] = []
            for child in _iter_named_children(root):
                if child.kind() != "export_statement":
                    continue
                _emit_export_symbols(child, stem, content_bytes, symbols)
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


LANGUAGE = JavaScriptPlugin()
