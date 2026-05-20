"""F# language plugin — hand-rolled regex / indentation-aware scanner.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``'s "F# (``languages/fsharp.py``)"
section. F# has no mature tree-sitter grammar so this module ships its own
small scanner: tokenize line-by-line, regex-match the start of each construct
(``namespace`` / ``module`` / ``open`` / ``type`` / ``let`` / ``let rec`` /
``member``), track an indentation-aware scope stack, and close each chunk at
the next sibling-or-shallower construct or at EOF.

The plugin reads ``.fsproj`` to recover compile-order semantics. Discovery has
two modes:

* **Default** (``LANGUAGE = FSharpPlugin()``): walk parent directories from
  the parsed file's directory until a ``*.fsproj`` is found, capped at a
  depth of 6. The walk result and the parsed ``<Compile Include>`` order are
  cached per ``.fsproj`` path on the plugin instance; a "no ``.fsproj``"
  warning is emitted once per directory via ``write_log_stderr``.
* **Override** (``FSharpPlugin(fsproj_path=...)``): use the caller-supplied
  ``.fsproj`` for every parsed file in this process. No walking, no warnings
  on miss. Files not listed in the override's ``<Compile Include>`` simply
  have no ``fsproj_order`` recorded.

Storage form for the per-file compile order: appended to ``Chunk.scope`` as a
``|fsproj=<N>`` suffix (Option A from ``007.context.md``). When the file is
not in the project (or no project is found) the suffix is absent; chunks
without a meaningful enclosing scope keep ``scope=None``.

Parsing never raises in the default path — malformed regions either skip or
produce best-effort chunks.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from code_index.errors import write_log_stderr

from .protocol import Chunk, Edge, Symbol

# Maximum number of parent directories to walk looking for a `.fsproj`.
_FSPROJ_WALK_DEPTH: int = 6


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

# Each pattern matches the start of a construct. ``indent`` is captured so the
# scanner can compare indentation depth between sibling constructs.

_RE_NAMESPACE = re.compile(r"^(?P<indent>\s*)namespace\s+(?P<name>[A-Za-z_][\w.]*)")
_RE_MODULE = re.compile(
    r"^(?P<indent>\s*)module\s+(?:(?:rec|public|private|internal)\s+)*(?P<name>[A-Za-z_][\w.]*)"
)
_RE_OPEN = re.compile(r"^\s*open(?:\s+type)?\s+(?P<target>[A-Za-z_][\w.]*)")
_RE_TYPE = re.compile(
    r"^(?P<indent>\s*)type\s+(?:(?:rec|and)\s+)?(?P<name>[A-Za-z_]\w*)"
)
_RE_LET = re.compile(
    r"^(?P<indent>\s*)(?:and\s+|let\s+)(?:rec\s+|mutable\s+|inline\s+|private\s+|internal\s+|public\s+)*"
    r"(?P<name>[A-Za-z_]\w*|\(\s*[^)]+\s*\))"
)
_RE_MEMBER = re.compile(
    r"^(?P<indent>\s*)(?:static\s+|abstract\s+|override\s+|default\s+|member\s+)+"
    r"(?:(?:val|this|_)\s*\.)?(?P<name>[A-Za-z_]\w*)"
)

# DU case lines: leading ``|`` plus a capitalized identifier.
_RE_DU_CASE = re.compile(r"^(?P<indent>\s*)\|\s*(?P<name>[A-Z]\w*)")

# Attribute and doc-comment lines we should skip when determining the
# "structural" indent of a construct (we still include them in chunk text).
_RE_ATTR = re.compile(r"^\s*\[<")
_RE_DOC_COMMENT = re.compile(r"^\s*///")
_RE_BLANK_OR_COMMENT = re.compile(r"^\s*(?://.*)?$")


# ---------------------------------------------------------------------------
# Scope-stack frame for the scanner.
# ---------------------------------------------------------------------------


@dataclass
class _Frame:
    """One entry on the indentation-aware scope stack.

    ``kind`` is the construct kind (``"namespace"`` / ``"module"`` / ``"type"``
    / ``"function"`` / ``"member"``). ``name`` is the declared identifier.
    ``indent`` is the column at which the construct begins (length of the
    leading whitespace). The scanner pops frames whose indent is greater than
    or equal to the next construct's indent.
    """

    kind: str
    name: str
    indent: int
    start_line: int


@dataclass
class _Opener:
    """A detected construct opener as seen on a single line."""

    kind: str
    name: str
    indent: int


@dataclass
class _Construct:
    """A construct after its end line and DU cases have been resolved."""

    start_line: int
    end_line: int
    kind: str
    name: str
    scope: str | None
    indent: int
    du_cases: list[tuple[str, int]]


# ---------------------------------------------------------------------------
# fsproj parsing + cache
# ---------------------------------------------------------------------------


def _parse_fsproj(fsproj_path: Path) -> dict[Path, int]:
    """Parse a ``.fsproj`` and return ``{absolute compile path: 0-based order}``.

    Best-effort: any I/O or XML failure yields an empty mapping. The caller
    decides whether to warn; this helper is purely about extraction.
    """
    mapping: dict[Path, int] = {}
    try:
        text = fsproj_path.read_text(encoding="utf-8")
    except OSError:
        return mapping
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return mapping

    base = fsproj_path.parent
    order = 0
    # ``Compile`` elements may live under the default MSBuild namespace; iter
    # by local name to be namespace-agnostic.
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag != "Compile":
            continue
        include = elem.get("Include")
        if not include:
            continue
        # MSBuild paths use backslashes; normalize to forward slashes for
        # resolution. ``Path`` itself handles both on Windows.
        normalized = include.replace("\\", "/")
        try:
            resolved = (base / normalized).resolve()
        except OSError:
            continue
        mapping[resolved] = order
        order += 1
    return mapping


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------


class FSharpPlugin:
    """Hand-rolled plugin for ``.fs`` / ``.fsi`` / ``.fsx`` source.

    Constructor takes an optional ``fsproj_path``; when given the plugin uses
    that ``.fsproj`` for every file and never walks parent directories. When
    ``None`` (the default — and the form used by the registry export) it walks
    parent directories per ``007.context.md``.
    """

    name: str = "fsharp"
    extensions: tuple[str, ...] = (".fs", ".fsi", ".fsx")

    def __init__(self, fsproj_path: Path | None = None) -> None:
        self._override: Path | None = fsproj_path.resolve() if fsproj_path else None
        # Cache: fsproj absolute path -> {compile path -> order index}.
        self._fsproj_cache: dict[Path, dict[Path, int]] = {}
        # Walk-result cache: directory -> resolved fsproj path or None.
        self._dir_to_fsproj: dict[Path, Path | None] = {}
        # Directories we've already warned about (to avoid repeat spam).
        self._warned_dirs: set[Path] = set()

    # ----- Public API --------------------------------------------------

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        try:
            return self._chunk_impl(path, content)
        except Exception:
            return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        try:
            return self._symbols_impl(path, content)
        except Exception:
            return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        try:
            return self._imports_impl(path, content)
        except Exception:
            return []

    # ----- fsproj lookup ----------------------------------------------

    def _fsproj_order_for(self, path: Path) -> int | None:
        """Return the compile-order index for ``path``, or ``None``.

        Consults the override when set; otherwise walks parents (depth-bounded)
        looking for a ``*.fsproj`` and caches the result per directory.
        """
        if self._override is not None:
            mapping = self._mapping_for(self._override)
            try:
                resolved = path.resolve()
            except OSError:
                return None
            return mapping.get(resolved)

        try:
            start_dir = path.resolve().parent
        except OSError:
            return None

        fsproj = self._discover_fsproj(start_dir)
        if fsproj is None:
            return None
        mapping = self._mapping_for(fsproj)
        try:
            resolved = path.resolve()
        except OSError:
            return None
        return mapping.get(resolved)

    def _mapping_for(self, fsproj_path: Path) -> dict[Path, int]:
        cached = self._fsproj_cache.get(fsproj_path)
        if cached is not None:
            return cached
        mapping = _parse_fsproj(fsproj_path)
        self._fsproj_cache[fsproj_path] = mapping
        return mapping

    def _discover_fsproj(self, start_dir: Path) -> Path | None:
        """Walk up from ``start_dir`` looking for any ``*.fsproj``.

        Result is cached per starting directory. Returns the absolute path on
        success; on miss returns ``None`` and emits a one-shot warning via
        ``write_log_stderr`` per starting directory.
        """
        if start_dir in self._dir_to_fsproj:
            return self._dir_to_fsproj[start_dir]

        current: Path = start_dir
        for _ in range(_FSPROJ_WALK_DEPTH):
            try:
                candidates = sorted(current.glob("*.fsproj"))
            except OSError:
                candidates = []
            if candidates:
                resolved = candidates[0].resolve()
                self._dir_to_fsproj[start_dir] = resolved
                return resolved
            parent = current.parent
            if parent == current:
                break
            current = parent

        # No fsproj found anywhere up the chain. Warn at most once per
        # starting directory.
        self._dir_to_fsproj[start_dir] = None
        if start_dir not in self._warned_dirs:
            self._warned_dirs.add(start_dir)
            write_log_stderr(
                f"warning: no .fsproj found for {start_dir}; "
                "scope ordering may be wrong"
            )
        return None

    # ----- chunking + scope tracking ----------------------------------

    def _decorate_scope(self, base_scope: str | None, order: int | None) -> str | None:
        """Append the ``|fsproj=<N>`` suffix to ``base_scope`` when applicable."""
        if order is None:
            return base_scope
        if base_scope is None or base_scope == "":
            return f"|fsproj={order}"
        return f"{base_scope}|fsproj={order}"

    def _chunk_impl(self, path: Path, content: str) -> list[Chunk]:
        lines = content.splitlines(keepends=True)
        order = self._fsproj_order_for(path)
        constructs = self._scan_constructs(lines)

        chunks: list[Chunk] = []
        for c in constructs:
            text = "".join(lines[c.start_line - 1 : c.end_line])
            chunks.append(
                Chunk(
                    start_line=c.start_line,
                    end_line=c.end_line,
                    kind=c.kind,
                    name=c.name,
                    scope=self._decorate_scope(c.scope, order),
                    text=text,
                )
            )
        return chunks

    def _symbols_impl(self, path: Path, content: str) -> list[Symbol]:
        lines = content.splitlines(keepends=True)
        constructs = self._scan_constructs(lines)

        symbols: list[Symbol] = []
        for c in constructs:
            if not c.name:
                continue
            # The "module" / "namespace" file-level frames also surface as
            # def symbols; this matches the architecture doc's "module-qualified
            # names" intent so the scope prefix itself is searchable. Scope at
            # this layer is undecorated (the ``|fsproj=`` suffix is applied
            # only in ``_chunk_impl``).
            qualified = f"{c.scope}.{c.name}" if c.scope else c.name
            symbols.append(Symbol(name=qualified, kind="def", line=c.start_line))
            # Discriminated union cases: scan within the type's chunk text for
            # ``| CaseName`` lines and emit one symbol per case.
            if c.kind == "type":
                for case_name, case_line in c.du_cases:
                    case_qualified = f"{qualified}.{case_name}"
                    symbols.append(
                        Symbol(name=case_qualified, kind="def", line=case_line)
                    )
        return symbols

    def _imports_impl(self, path: Path, content: str) -> list[Edge]:
        edges: list[Edge] = []
        for idx, line in enumerate(content.splitlines(), start=1):
            m = _RE_OPEN.match(line)
            if m:
                edges.append(
                    Edge(
                        target=m.group("target"),
                        kind="import",
                        line=idx,
                        meta=None,
                    )
                )
        return edges

    # ----- the scanner ------------------------------------------------

    def _scan_constructs(self, lines: list[str]) -> list[_Construct]:
        """Return a list of constructs in source order with end lines resolved.

        Each construct carries its (1-based, inclusive) line range, its kind,
        its declared name, and the dotted enclosing scope at the point it
        opened. ``type``-kind constructs additionally carry the list of
        discriminated-union case names paired with the line they appear on.
        """
        # First pass: detect openers and the scope each one sees.
        opener_records: list[tuple[int, _Opener, str | None]] = []
        # Frame stack: persistent, used to compute ``scope`` at the point of
        # each opener.
        stack: list[_Frame] = []

        for idx, raw in enumerate(lines, start=1):
            stripped = raw.rstrip("\n")
            # Skip blank, attribute, and doc-comment lines for structural
            # purposes — they're absorbed into the next construct's chunk.
            if _RE_BLANK_OR_COMMENT.match(stripped):
                continue
            if _RE_ATTR.match(stripped) or _RE_DOC_COMMENT.match(stripped):
                continue

            opener = self._match_opener(stripped)
            if opener is None:
                continue

            # Pop frames at >= this indent — they are siblings or outer scopes.
            # Namespace is special: a ``namespace X`` declaration introduces a
            # file-scope container with no indentation contract; subsequent
            # module/type declarations at column 0 are still its children.
            # Treat namespace frames as immortal here (never popped by indent).
            while (
                stack
                and stack[-1].indent >= opener.indent
                and stack[-1].kind != "namespace"
            ):
                stack.pop()

            scope = self._scope_string(stack)
            opener_records.append((idx, opener, scope))

            # Push this frame on the stack only if it can contain children.
            # ``namespace``, ``module``, ``type`` are containers; ``function``
            # is a leaf for our scope purposes.
            if opener.kind in ("namespace", "module", "type"):
                stack.append(
                    _Frame(
                        kind=opener.kind,
                        name=opener.name,
                        indent=opener.indent,
                        start_line=idx,
                    )
                )

        # Second pass: compute end_line for each opener. An opener's chunk
        # extends until the next opener whose indent is <= our indent
        # (sibling-or-shallower), or EOF.
        results: list[_Construct] = []
        n = len(opener_records)
        for i, (start_line, op, scope) in enumerate(opener_records):
            end_line = len(lines)
            for j in range(i + 1, n):
                nxt_start, nxt_op, _ = opener_records[j]
                if nxt_op.indent <= op.indent:
                    end_line = nxt_start - 1
                    break
            # Trim trailing blank lines so chunks don't drag whitespace.
            while end_line > start_line and lines[end_line - 1].strip() == "":
                end_line -= 1

            du_cases: list[tuple[str, int]] = []
            if op.kind == "type":
                du_cases = self._collect_du_cases(lines, start_line, end_line, op.indent)

            results.append(
                _Construct(
                    start_line=start_line,
                    end_line=end_line,
                    kind=op.kind,
                    name=op.name,
                    scope=scope,
                    indent=op.indent,
                    du_cases=du_cases,
                )
            )
        return results

    def _match_opener(self, line: str) -> _Opener | None:
        """Classify ``line`` as a construct opener, or return ``None``.

        Order matters — ``member`` must be checked before ``let`` because the
        ``static member`` form would otherwise look like a stray ``static`` to
        the ``let`` regex (which it isn't, but defensive ordering is cheaper
        than reasoning about each new keyword).
        """
        m = _RE_NAMESPACE.match(line)
        if m:
            return _Opener(kind="namespace", name=m.group("name"), indent=len(m.group("indent")))
        m = _RE_MODULE.match(line)
        if m:
            return _Opener(kind="module", name=m.group("name"), indent=len(m.group("indent")))
        m = _RE_TYPE.match(line)
        if m:
            return _Opener(kind="type", name=m.group("name"), indent=len(m.group("indent")))
        m = _RE_MEMBER.match(line)
        if m:
            return _Opener(kind="function", name=m.group("name"), indent=len(m.group("indent")))
        m = _RE_LET.match(line)
        if m:
            return _Opener(kind="function", name=m.group("name"), indent=len(m.group("indent")))
        return None

    def _scope_string(self, stack: list[_Frame]) -> str | None:
        """Compose the dotted enclosing scope from ``stack``.

        Includes every frame's name in order.
        """
        if not stack:
            return None
        return ".".join(frame.name for frame in stack)

    def _collect_du_cases(
        self, lines: list[str], start: int, end: int, type_indent: int
    ) -> list[tuple[str, int]]:
        """Scan ``[start+1, end]`` for DU ``| CaseName`` lines.

        Only lines indented deeper than the type opener and matching the DU
        case regex contribute.
        """
        cases: list[tuple[str, int]] = []
        for idx in range(start + 1, end + 1):
            line = lines[idx - 1].rstrip("\n")
            m = _RE_DU_CASE.match(line)
            if not m:
                continue
            if len(m.group("indent")) <= type_indent:
                continue
            cases.append((m.group("name"), idx))
        return cases


LANGUAGE = FSharpPlugin()
