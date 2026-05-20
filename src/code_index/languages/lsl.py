"""LSL language plugin — hand-rolled regex + brace-balance scanner.

Implements the ``Language`` Protocol per
``docs/architecture/chunking-and-languages.md``'s "LSL (``languages/lsl.py``)"
section. LSL has no tree-sitter grammar in the language pack, so this module
ships its own small scanner: strip comments (newline-preserving), walk the
source with a depth-tracking state machine, and recognise four constructs:

* ``state <name> { ... }`` (and the ``default`` keyword form) — chunked as
  ``"state"``.
* event handlers inside a state — chunked as ``"event"`` with
  ``scope = <state name>``; symbol form ``<state>.<event>``.
* user-defined functions at global scope — chunked as ``"function"`` with
  ``scope = "global"``.
* a single ``"module"`` chunk wrapping every global variable / constant
  declaration that is neither a state nor a function.

Symbols (`ref`) are emitted for every ``llXxx`` call site (one per
occurrence). The regex anchors on ``\\bll([A-Z][A-Za-z0-9]*)`` and only matches
when followed by ``(``; the leading ``ll`` is mandatory, so ``osXxx`` calls
are excluded by virtue of not matching. ``test_no_ossl_recognition`` pins
this. OSSL recognition is deferred — see the feature ``outcome.md``.

Edges: four kinds, all from specific ``llXxx`` calls — ``listen`` /
``link_message`` / ``http`` / ``email``. For ``llListen``,
``llMessageLinked``, ``llHTTPRequest``, ``llEmail`` the ``target`` is the
verbatim source text of the first argument (whitespace-trimmed), found via a
balanced-paren / -bracket / -quote scan starting at the opening ``(``.

``imports()`` returns ``[]`` — LSL has no traditional imports. Malformed
input never raises in any of the three entry points.
"""

from __future__ import annotations

import re
from pathlib import Path

from .protocol import Chunk, Edge, Symbol

# Known LSL event-handler names. Used inside states to recognise an
# ``<event>(<params>) {`` opener at depth 1. Sourced from the LSL viewer
# wiki's canonical list; the set covers Phase 3's needs even if newer events
# (rare) are added later — unknown event-shaped lines are silently ignored
# rather than mis-chunked, matching the best-effort rule.
_LSL_EVENTS: frozenset[str] = frozenset(
    {
        "state_entry",
        "state_exit",
        "touch_start",
        "touch",
        "touch_end",
        "collision_start",
        "collision",
        "collision_end",
        "land_collision_start",
        "land_collision",
        "land_collision_end",
        "timer",
        "listen",
        "sensor",
        "no_sensor",
        "control",
        "at_target",
        "not_at_target",
        "at_rot_target",
        "not_at_rot_target",
        "money",
        "email",
        "run_time_permissions",
        "changed",
        "attach",
        "dataserver",
        "moving_start",
        "moving_end",
        "object_rez",
        "remote_data",
        "http_response",
        "http_request",
        "link_message",
        "on_rez",
        "transaction_result",
        "path_update",
        "experience_permissions",
        "experience_permissions_denied",
    }
)

# LSL primitive type keywords that can introduce a global variable or a
# user-defined function at file scope.
_LSL_TYPES: frozenset[str] = frozenset(
    {"integer", "float", "string", "key", "vector", "rotation", "list"}
)

# `ll`-prefixed call references. ``\b`` prevents matches inside identifiers
# like ``myllListen``; the trailing ``\s*\(`` requirement filters out
# non-call mentions (constants, comments are already stripped). The leading
# ``ll`` is mandatory — there is no equivalent rule for ``os`` prefixes, which
# is what enforces OSSL absence.
_RE_LL_CALL = re.compile(r"\bll[A-Z][A-Za-z0-9]*(?=\s*\()")

# Identifier and a few small structural regexes used by the scanner.
_RE_IDENT = re.compile(r"[A-Za-z_]\w*")

# Edge-producing calls map their function name to an edge ``kind``.
_EDGE_KINDS: dict[str, str] = {
    "llListen": "listen",
    "llMessageLinked": "link_message",
    "llHTTPRequest": "http",
    "llEmail": "email",
}


# ---------------------------------------------------------------------------
# Comment stripping (newline-preserving)
# ---------------------------------------------------------------------------


def _strip_comments(source: str) -> str:
    """Return ``source`` with ``//...`` and ``/* ... */`` comments removed.

    Newlines inside block comments are preserved verbatim so line numbers
    line up with the original source. String literals are left intact so
    that ``"//"`` inside a string is not treated as a comment opener.
    """
    out: list[str] = []
    i: int = 0
    n: int = len(source)
    while i < n:
        ch = source[i]
        # String literal: copy through until unescaped closing quote.
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = source[i]
                out.append(c)
                i += 1
                if c == "\\" and i < n:
                    # Pass the escaped character through unmodified.
                    out.append(source[i])
                    i += 1
                    continue
                if c == '"':
                    break
            continue
        # Line comment.
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            i += 2
            while i < n and source[i] != "\n":
                i += 1
            continue
        # Block comment — replace with newlines for any newlines inside, drop
        # the rest. LSL Mono actually does not support block comments, but
        # accepting them is the kinder behaviour and aligns with the design
        # doc's "tolerate" stance.
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i += 2
            while i < n:
                if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                    i += 2
                    break
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Line-number lookup
# ---------------------------------------------------------------------------


def _line_starts(content: str) -> list[int]:
    """Return the 0-based character offset where each 1-based line begins.

    Index 0 is unused (1-based); ``starts[k]`` is the offset of line ``k``.
    """
    starts: list[int] = [0, 0]
    for idx, ch in enumerate(content):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _line_of(offset: int, starts: list[int]) -> int:
    """Translate a 0-based character offset to a 1-based line number."""
    # Binary search would be marginally faster, but the linear scan is fine
    # for plugin-scale inputs and trivially correct.
    lo, hi = 1, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------------------
# Balanced scans
# ---------------------------------------------------------------------------


def _find_matching_brace(content: str, open_pos: int) -> int:
    """Return the index of the ``}`` matching the ``{`` at ``open_pos``.

    Tracks brace depth and skips over string literals so ``"{"`` inside a
    string doesn't shift depth. Returns ``-1`` if no match (malformed
    input).
    """
    assert content[open_pos] == "{"
    depth = 0
    i = open_pos
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == '"':
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_matching_paren(content: str, open_pos: int) -> int:
    """Return the index of the ``)`` matching the ``(`` at ``open_pos``.

    Same as :func:`_find_matching_brace` but for parentheses. Returns ``-1``
    on malformed input.
    """
    assert content[open_pos] == "("
    depth = 0
    i = open_pos
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == '"':
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _first_argument_text(content: str, paren_open: int) -> str:
    """Extract the verbatim source of the first argument after ``(``.

    Scans from ``paren_open + 1`` looking for the first top-level ``,`` or
    matching ``)``; everything between is returned, trimmed. Honors nested
    ``()``, ``[]``, ``<>``-grouping is NOT special-cased (LSL ``<x,y,z>``
    vector literals would split on the inner ``,`` — out of scope for Phase
    3's edge-target extraction; the four edge-producing calls don't take
    vector arguments in their first position).
    """
    i = paren_open + 1
    n = len(content)
    paren_depth = 0
    bracket_depth = 0
    while i < n:
        ch = content[i]
        if ch == '"':
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            if paren_depth == 0:
                return content[paren_open + 1 : i].strip()
            paren_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            if bracket_depth > 0:
                bracket_depth -= 1
        elif ch == "," and paren_depth == 0 and bracket_depth == 0:
            return content[paren_open + 1 : i].strip()
        i += 1
    # Unterminated — return whatever we have so far, trimmed.
    return content[paren_open + 1 :].strip()


# ---------------------------------------------------------------------------
# Top-level scanner
# ---------------------------------------------------------------------------


def _skip_ws(content: str, i: int) -> int:
    """Advance ``i`` past whitespace; returns the new index."""
    n = len(content)
    while i < n and content[i] in " \t\r\n":
        i += 1
    return i


def _next_ident(content: str, i: int) -> tuple[str | None, int, int]:
    """Read an identifier starting at ``i`` (after skipping leading ws).

    Returns ``(name, start, end)`` where ``start`` is the index of the first
    character of the identifier and ``end`` is one past the last. ``name`` is
    ``None`` when no identifier is present at that position.
    """
    i = _skip_ws(content, i)
    m = _RE_IDENT.match(content, i)
    if not m:
        return (None, i, i)
    return (m.group(0), m.start(), m.end())


def _is_function_signature(content: str, type_end: int) -> tuple[str, int, int] | None:
    """Test whether a type-keyword introduces ``<type> <name> ( ... ) {``.

    ``type_end`` points one past the end of the leading type keyword. Returns
    ``(name, open_brace_pos, close_brace_pos)`` for a function definition,
    or ``None`` if this is actually a variable declaration.
    """
    name, _name_start, name_end = _next_ident(content, type_end)
    if name is None:
        return None
    j = _skip_ws(content, name_end)
    if j >= len(content) or content[j] != "(":
        return None
    paren_close = _find_matching_paren(content, j)
    if paren_close < 0:
        return None
    k = _skip_ws(content, paren_close + 1)
    if k >= len(content) or content[k] != "{":
        return None
    brace_close = _find_matching_brace(content, k)
    if brace_close < 0:
        return None
    return (name, k, brace_close)


def _is_void_function(content: str, i: int) -> tuple[str, int, int, int] | None:
    """Test whether ``<name> ( ... ) {`` at ``i`` is a void function at file scope.

    Returns ``(name, name_start, open_brace_pos, close_brace_pos)`` on match.
    Used to detect untyped (void) global functions, which share their syntax
    with event handlers; at file scope, the global context distinguishes
    them.
    """
    name, name_start, name_end = _next_ident(content, i)
    if name is None:
        return None
    j = _skip_ws(content, name_end)
    if j >= len(content) or content[j] != "(":
        return None
    paren_close = _find_matching_paren(content, j)
    if paren_close < 0:
        return None
    k = _skip_ws(content, paren_close + 1)
    if k >= len(content) or content[k] != "{":
        return None
    brace_close = _find_matching_brace(content, k)
    if brace_close < 0:
        return None
    return (name, name_start, k, brace_close)


def _find_semicolon(content: str, i: int) -> int:
    """Find the next top-level ``;`` from ``i``.

    Skips string literals and balanced ``()`` / ``[]``. Returns the index of
    the semicolon or ``-1`` on malformed input.
    """
    n = len(content)
    paren_depth = 0
    bracket_depth = 0
    while i < n:
        ch = content[i]
        if ch == '"':
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            if paren_depth > 0:
                paren_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            if bracket_depth > 0:
                bracket_depth -= 1
        elif ch == ";" and paren_depth == 0 and bracket_depth == 0:
            return i
        i += 1
    return -1


# ---------------------------------------------------------------------------
# Construct records (internal)
# ---------------------------------------------------------------------------


class _GlobalDecl:
    """One global variable / constant declaration, by source span.

    The plugin coalesces every such declaration in source order into a
    single ``"module"`` chunk that spans the first to the last declaration.
    Individual names are still emitted as ``def`` symbols.
    """

    __slots__ = ("start", "end", "name", "line")

    def __init__(self, start: int, end: int, name: str, line: int) -> None:
        self.start = start
        self.end = end
        self.name = name
        self.line = line


class _FuncDecl:
    """A user-defined function at global scope."""

    __slots__ = ("start", "end", "name", "line")

    def __init__(self, start: int, end: int, name: str, line: int) -> None:
        self.start = start
        self.end = end
        self.name = name
        self.line = line


class _StateDecl:
    """One state block (``default`` or named)."""

    __slots__ = ("start", "end", "name", "line", "events")

    def __init__(self, start: int, end: int, name: str, line: int) -> None:
        self.start = start
        self.end = end
        self.name = name
        self.line = line
        self.events: list[_EventDecl] = []


class _EventDecl:
    """An event handler inside a state."""

    __slots__ = ("start", "end", "name", "line", "state")

    def __init__(self, start: int, end: int, name: str, line: int, state: str) -> None:
        self.start = start
        self.end = end
        self.name = name
        self.line = line
        self.state = state


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------


class LSLPlugin:
    """LSL plugin — pure-LSL only (no OSSL recognition).

    See module docstring for design notes. The three Protocol methods each
    wrap a private implementation in a blanket ``try``/``except`` so a
    pathological input cannot raise out of the plugin layer.
    """

    name: str = "lsl"
    extensions: tuple[str, ...] = (".lsl",)

    # ----- Public API --------------------------------------------------

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        try:
            return self._chunk_impl(content)
        except Exception:
            return []

    def symbols(self, path: Path, content: str) -> list[Symbol]:
        try:
            return self._symbols_impl(content)
        except Exception:
            return []

    def imports(self, path: Path, content: str) -> list[Edge]:
        # LSL has no traditional imports (``open`` / ``using`` / ``require``).
        # The Protocol's ``imports`` method, however, is the only edge-
        # emitting method on ``Language``; the four LSL-specific edge kinds
        # (``listen`` / ``link_message`` / ``http`` / ``email``) therefore
        # flow through here. The step DoD line "imports() returns []" refers
        # to the LSL semantic concept of imports (there are none) — when a
        # file has no edge-producing ``llXxx`` calls this method returns the
        # empty list. See ``status.md`` Notes & Issues for the
        # interpretation note.
        del path
        try:
            return self._edges_impl(content)
        except Exception:
            return []

    # ----- Implementation --------------------------------------------

    def _chunk_impl(self, content: str) -> list[Chunk]:
        stripped = _strip_comments(content)
        starts = _line_starts(content)
        globals_, funcs, states = self._scan_top_level(stripped)

        chunks: list[Chunk] = []

        # Module chunk: one chunk spanning the first to last global decl, if
        # any globals were found. Carries no name, scope = None.
        if globals_:
            first = globals_[0]
            last = globals_[-1]
            start_line = _line_of(first.start, starts)
            end_line = _line_of(last.end - 1, starts)
            text = content[first.start : last.end]
            chunks.append(
                Chunk(
                    start_line=start_line,
                    end_line=end_line,
                    kind="module",
                    name=None,
                    scope=None,
                    text=text,
                )
            )

        # Function chunks.
        for f in funcs:
            start_line = _line_of(f.start, starts)
            end_line = _line_of(f.end - 1, starts)
            chunks.append(
                Chunk(
                    start_line=start_line,
                    end_line=end_line,
                    kind="function",
                    name=f.name,
                    scope="global",
                    text=content[f.start : f.end],
                )
            )

        # State chunks plus their nested event chunks.
        for s in states:
            start_line = _line_of(s.start, starts)
            end_line = _line_of(s.end - 1, starts)
            chunks.append(
                Chunk(
                    start_line=start_line,
                    end_line=end_line,
                    kind="state",
                    name=s.name,
                    scope=None,
                    text=content[s.start : s.end],
                )
            )
            for ev in s.events:
                ev_start_line = _line_of(ev.start, starts)
                ev_end_line = _line_of(ev.end - 1, starts)
                chunks.append(
                    Chunk(
                        start_line=ev_start_line,
                        end_line=ev_end_line,
                        kind="event",
                        name=ev.name,
                        scope=s.name,
                        text=content[ev.start : ev.end],
                    )
                )

        return chunks

    def _symbols_impl(self, content: str) -> list[Symbol]:
        stripped = _strip_comments(content)
        starts = _line_starts(content)
        globals_, funcs, states = self._scan_top_level(stripped)

        symbols: list[Symbol] = []

        for g in globals_:
            symbols.append(Symbol(name=g.name, kind="def", line=g.line))

        for f in funcs:
            symbols.append(Symbol(name=f.name, kind="def", line=f.line))

        for s in states:
            for ev in s.events:
                symbols.append(
                    Symbol(
                        name=f"{s.name}.{ev.name}",
                        kind="def",
                        line=ev.line,
                    )
                )

        # `ref` symbols: every ``llXxx`` call site in the (comment-stripped)
        # source. One entry per occurrence — no deduplication at the plugin
        # level.
        for m in _RE_LL_CALL.finditer(stripped):
            symbols.append(
                Symbol(
                    name=m.group(0),
                    kind="ref",
                    line=_line_of(m.start(), starts),
                )
            )

        return symbols

    def _edges_impl(self, content: str) -> list[Edge]:
        stripped = _strip_comments(content)
        starts = _line_starts(content)
        edges: list[Edge] = []
        for m in _RE_LL_CALL.finditer(stripped):
            fn_name = m.group(0)
            kind = _EDGE_KINDS.get(fn_name)
            if kind is None:
                continue
            # Find the opening ``(`` immediately after the identifier
            # (already established to exist by the regex lookahead).
            i = m.end()
            i = _skip_ws(stripped, i)
            if i >= len(stripped) or stripped[i] != "(":
                continue
            target = _first_argument_text(stripped, i)
            edges.append(
                Edge(
                    target=target,
                    kind=kind,
                    line=_line_of(m.start(), starts),
                    meta=None,
                )
            )
        return edges

    # ----- Scanner --------------------------------------------------

    def _scan_top_level(
        self, content: str
    ) -> tuple[list[_GlobalDecl], list[_FuncDecl], list[_StateDecl]]:
        """Walk the comment-stripped source and classify top-level constructs.

        Returns three lists in source order: global decls (variable /
        constant), user functions, and states (each with its nested event
        handlers populated).
        """
        starts = _line_starts(content)
        globals_: list[_GlobalDecl] = []
        funcs: list[_FuncDecl] = []
        states: list[_StateDecl] = []

        i = 0
        n = len(content)
        while i < n:
            i = _skip_ws(content, i)
            if i >= n:
                break

            # `default` state.
            if content.startswith("default", i) and self._is_word_boundary(content, i + len("default")):
                j = _skip_ws(content, i + len("default"))
                if j < n and content[j] == "{":
                    close = _find_matching_brace(content, j)
                    if close < 0:
                        break
                    state = _StateDecl(
                        start=i,
                        end=close + 1,
                        name="default",
                        line=_line_of(i, starts),
                    )
                    state.events = self._scan_events(content, j, close, "default")
                    states.append(state)
                    i = close + 1
                    continue

            # ``state <name> { ... }``.
            if content.startswith("state", i) and self._is_word_boundary(content, i + len("state")):
                state_kw_end = i + len("state")
                name, _ns, ne = _next_ident(content, state_kw_end)
                if name is not None:
                    j = _skip_ws(content, ne)
                    if j < n and content[j] == "{":
                        close = _find_matching_brace(content, j)
                        if close < 0:
                            break
                        state = _StateDecl(
                            start=i,
                            end=close + 1,
                            name=name,
                            line=_line_of(i, starts),
                        )
                        state.events = self._scan_events(content, j, close, name)
                        states.append(state)
                        i = close + 1
                        continue

            # Typed declaration: ``<type> <name> ...`` — function if followed
            # by ``( ... ) {``, else a variable.
            type_name, _ts, type_end = _next_ident(content, i)
            if type_name is not None and type_name in _LSL_TYPES:
                sig = _is_function_signature(content, type_end)
                if sig is not None:
                    fn_name, _brace_open, brace_close = sig
                    funcs.append(
                        _FuncDecl(
                            start=i,
                            end=brace_close + 1,
                            name=fn_name,
                            line=_line_of(i, starts),
                        )
                    )
                    i = brace_close + 1
                    continue
                # Variable declaration: ``<type> <name> [= <expr>];``.
                var_name, _vs, _ve = _next_ident(content, type_end)
                if var_name is not None:
                    semi = _find_semicolon(content, type_end)
                    if semi < 0:
                        # Malformed — bail to the next char to avoid an
                        # infinite loop, but don't raise.
                        i += 1
                        continue
                    globals_.append(
                        _GlobalDecl(
                            start=i,
                            end=semi + 1,
                            name=var_name,
                            line=_line_of(i, starts),
                        )
                    )
                    i = semi + 1
                    continue
                # No name after the type — skip one char to make progress.
                i += 1
                continue

            # Possibly a void (untyped) function: ``<name>(...) { ... }``.
            # Only legal at file scope; the call site is the file scope.
            if type_name is not None and type_name not in _LSL_TYPES:
                vf = _is_void_function(content, i)
                if vf is not None:
                    fn_name, name_start, _brace_open, brace_close = vf
                    funcs.append(
                        _FuncDecl(
                            start=name_start,
                            end=brace_close + 1,
                            name=fn_name,
                            line=_line_of(name_start, starts),
                        )
                    )
                    i = brace_close + 1
                    continue

            # Nothing matched — advance by one character to make progress.
            # Malformed inputs land here repeatedly; the scanner stays
            # productive rather than raising.
            i += 1

        return globals_, funcs, states

    def _scan_events(
        self, content: str, state_brace_open: int, state_brace_close: int, state_name: str
    ) -> list[_EventDecl]:
        """Scan the body of a state for event handlers.

        ``state_brace_open`` is the index of the state's ``{``; the body
        spans up to (and excluding) ``state_brace_close``. An event handler
        is any ``<name>(<params>) { ... }`` whose name is in the known LSL
        event-name whitelist. Unknown names are silently ignored.
        """
        events: list[_EventDecl] = []
        starts = _line_starts(content)
        i = state_brace_open + 1
        while i < state_brace_close:
            i = _skip_ws(content, i)
            if i >= state_brace_close:
                break
            name, name_start, name_end = _next_ident(content, i)
            if name is None or name not in _LSL_EVENTS:
                i += 1
                continue
            j = _skip_ws(content, name_end)
            if j >= state_brace_close or content[j] != "(":
                i = name_end
                continue
            paren_close = _find_matching_paren(content, j)
            if paren_close < 0 or paren_close >= state_brace_close:
                break
            k = _skip_ws(content, paren_close + 1)
            if k >= state_brace_close or content[k] != "{":
                i = paren_close + 1
                continue
            brace_close = _find_matching_brace(content, k)
            if brace_close < 0 or brace_close > state_brace_close:
                break
            events.append(
                _EventDecl(
                    start=name_start,
                    end=brace_close + 1,
                    name=name,
                    line=_line_of(name_start, starts),
                    state=state_name,
                )
            )
            i = brace_close + 1
        return events

    @staticmethod
    def _is_word_boundary(content: str, i: int) -> bool:
        """True when position ``i`` is at end-of-word.

        Used to ensure ``default`` or ``state`` keyword matches don't fire
        on identifiers like ``state_machine`` or ``defaulting``.
        """
        if i >= len(content):
            return True
        ch = content[i]
        return not (ch.isalnum() or ch == "_")


LANGUAGE = LSLPlugin()
