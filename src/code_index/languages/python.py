"""Python language plugin — stdlib ``ast``-based chunker.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``. Chunks are emitted for every
top-level / class-level ``def`` / ``async def`` / ``class`` declaration plus a
single ``module``-kind chunk collapsing any non-def, non-class, non-import
statements at module scope. Symbols are dotted intra-file names; imports are
edges with ``target`` computed per the table in ``002.context.md``.

Parsing is tolerant: on ``SyntaxError`` every method returns an empty list.
Phase 4 wraps plugin calls and decides whether to log per skip-or-strict.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .protocol import Chunk, Edge, Symbol

_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _parse(path: Path, content: str) -> ast.Module | None:
    try:
        return ast.parse(content, filename=str(path))
    except SyntaxError:
        return None


def _slice_lines(content: str, start: int, end: int) -> str:
    """Return the inclusive 1-based line range ``[start, end]`` from ``content``."""
    lines = content.splitlines(keepends=True)
    # 1-based inclusive → 0-based half-open.
    return "".join(lines[start - 1 : end])


def _chunk_kind(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    # FunctionDef and AsyncFunctionDef both map to "function".
    return "function"


def _join_scope(stack: tuple[str, ...]) -> str | None:
    return ".".join(stack) if stack else None


def _collect_defs(
    body: list[ast.stmt],
    scope: tuple[str, ...],
    out: list[tuple[ast.AST, tuple[str, ...]]],
) -> None:
    """Walk ``body`` and append every def/class node with its enclosing scope.

    Recurses into class and function bodies so nested defs surface with their
    dotted scope. Order is source order via a simple pre-order walk.
    """
    for node in body:
        if isinstance(node, _DEF_NODES):
            out.append((node, scope))
            inner_scope = scope + (node.name,)
            _collect_defs(node.body, inner_scope, out)


class PythonPlugin:
    """AST-aware plugin for ``.py`` source."""

    name = "python"
    extensions = (".py",)

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        tree = _parse(path, content)
        if tree is None:
            return []

        chunks: list[Chunk] = []

        # Module-body chunk: all top-level statements that are not def/class/import.
        module_stmts = [
            stmt
            for stmt in tree.body
            if not isinstance(stmt, _DEF_NODES)
            and not isinstance(stmt, (ast.Import, ast.ImportFrom))
        ]
        if module_stmts:
            start = module_stmts[0].lineno
            end_lineno = module_stmts[-1].end_lineno
            end = end_lineno if end_lineno is not None else start
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

        collected: list[tuple[ast.AST, tuple[str, ...]]] = []
        _collect_defs(tree.body, (), collected)
        for node, scope_stack in collected:
            assert isinstance(node, _DEF_NODES)
            start = node.lineno
            end_lineno = node.end_lineno
            end = end_lineno if end_lineno is not None else start
            chunks.append(
                Chunk(
                    start_line=start,
                    end_line=end,
                    kind=_chunk_kind(node),
                    name=node.name,
                    scope=_join_scope(scope_stack),
                    text=_slice_lines(content, start, end),
                )
            )

        return chunks

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        tree = _parse(path, content)
        if tree is None:
            return []

        collected: list[tuple[ast.AST, tuple[str, ...]]] = []
        _collect_defs(tree.body, (), collected)

        symbols: list[Symbol] = []
        for node, scope_stack in collected:
            assert isinstance(node, _DEF_NODES)
            dotted = ".".join(scope_stack + (node.name,))
            symbols.append(Symbol(name=dotted, kind="def", line=node.lineno))
        return symbols

    def imports(self, path: Path, content: str) -> list[Edge]:
        tree = _parse(path, content)
        if tree is None:
            return []

        edges: list[Edge] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(
                        Edge(target=alias.name, kind="import", line=node.lineno, meta=None)
                    )
            elif isinstance(node, ast.ImportFrom):
                dots = "." * node.level
                module = node.module or ""
                for alias in node.names:
                    if module:
                        target = f"{dots}{module}.{alias.name}"
                    elif dots:
                        # Relative import without a module: ``from . import x``.
                        target = f"{dots}{alias.name}"
                    else:
                        target = alias.name
                    edges.append(
                        Edge(target=target, kind="import", line=node.lineno, meta=None)
                    )
        return edges


LANGUAGE = PythonPlugin()
