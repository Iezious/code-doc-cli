# pyright: reportUnknownMemberType=false, reportGeneralTypeIssues=false
"""Typer CLI app — entry point for ``code_index`` and ``python -m code_index``.

Wires shared flags (``--config``, ``--format``, ``--verbose``, ``--quiet``)
at the app callback, registers every MVP subcommand from
``docs/architecture/cli.md`` (most as stubs raising
:class:`CodeIndexError` with kind :data:`Kinds.CLI_NOT_IMPLEMENTED`), and
implements ``config show`` end-to-end against the Phase 1 JSON shape
pinned in ``docs/plans/001.foundations/005.context.md``.

The boundary exception handler is installed via a :class:`BoundaryTyper`
subclass whose ``__call__`` routes uncaught exceptions through the stream
helpers in :mod:`code_index.errors`. ``CodeIndexError`` is reported using
its own ``code`` / ``kind`` / ``message``; any other exception is reported
as ``code=99, kind="unknown"`` per ``errors-and-exit-codes.md``.

Stream discipline: this module never calls ``print`` or writes to
``sys.stdout`` / ``sys.stderr`` directly. All output flows through helpers
in :mod:`code_index.errors``.
"""

from __future__ import annotations

import enum
import sqlite3
import sys
from pathlib import Path
from typing import Annotated, Any

import click
import typer

from code_index import embeddings, indexer, storage
from code_index import graph as graph_module
from code_index import search as search_module
from code_index import symbols as symbols_module
from code_index import sync as sync_module
from code_index.config import CodeIndexConfig, discover_config_path, load_config
from code_index.errors import (
    EXIT_CONFIG,
    EXIT_INDEX_MISSING,
    EXIT_INDEX_MODEL,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    CodeIndexError,
    Kinds,
    write_error_envelope_stdout,
    write_error_summary_stderr,
    write_json_stdout,
    write_result_stdout,
)
from code_index.init import write_skeleton
from code_index.languages.registry import active_plugins
from code_index.search import SearchFilters, SearchResult
from code_index.storage import get_meta, open_index

# Synthesized kind for unhandled exceptions; documented in the DoD-5 test.
_UNKNOWN_KIND: str = "unknown"


# ---------------------------------------------------------------------------
# Typer app + sub-typers.
#
# :class:`BoundaryTyper` wraps ``__call__`` so calling ``app()`` from
# ``[project.scripts]`` or ``python -m code_index`` routes uncaught
# :class:`CodeIndexError` instances through our stream helpers instead of
# letting Click print a traceback. All non-``CodeIndexError`` exceptions are
# routed as ``code=99, kind="unknown"`` per ``errors-and-exit-codes.md``.
# ---------------------------------------------------------------------------


class BoundaryTyper(typer.Typer):
    """``typer.Typer`` with our error-boundary discipline on ``__call__``."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        argv_kw: Any = kwargs.get("args")
        if isinstance(argv_kw, list):
            argv: list[str] = [str(token) for token in argv_kw]  # type: ignore[reportUnknownVariableType]
        elif args and isinstance(args[0], list):
            argv = [str(token) for token in args[0]]  # type: ignore[reportUnknownVariableType]
        else:
            argv = sys.argv[1:]
        raise SystemExit(_invoke(argv))


app: BoundaryTyper = BoundaryTyper(
    name="code_index",
    help="Per-project SQLite index with hybrid BM25 + dense retrieval.",
    no_args_is_help=True,
    add_completion=False,
)

index_app: typer.Typer = typer.Typer(
    name="index",
    help="Build, sync, or rebuild the per-project index.",
    no_args_is_help=True,
)
symbols_app: typer.Typer = typer.Typer(
    name="symbols",
    help="Lookup symbol definitions or references.",
    no_args_is_help=True,
)
graph_app: typer.Typer = typer.Typer(
    name="graph",
    help="Lightweight dep/call queries over the edges table.",
    no_args_is_help=True,
)
config_app: typer.Typer = typer.Typer(
    name="config",
    help="Inspect resolved configuration.",
    no_args_is_help=True,
)

app.add_typer(index_app, name="index")
app.add_typer(symbols_app, name="symbols")
app.add_typer(graph_app, name="graph")
app.add_typer(config_app, name="config")


# ---------------------------------------------------------------------------
# Top-level callback wiring shared flags.
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Override config discovery; path to a config.toml file."),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format: text|json. JSON puts results/envelopes on stdout."),
    ] = "text",
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Emit timings and pool sizes to stderr.")
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", help="Suppress stderr progress; stdout shape unchanged."),
    ] = False,
) -> None:
    """Shared flags. Resolved values are stored on ``ctx.obj`` for subcommands."""
    ctx.obj = {
        "config": config,
        "format": format,
        "verbose": verbose,
        "quiet": quiet,
    }


# ---------------------------------------------------------------------------
# Subcommand implementations — every MVP subcommand is real as of Phase 6
# step 004. The historical ``_stub`` helper that raised
# :data:`Kinds.CLI_NOT_IMPLEMENTED` for then-unimplemented commands was
# removed when the last stubs landed; reintroduce it (and its callers) if a
# future phase needs to ship a placeholder subcommand again.
# ---------------------------------------------------------------------------


@app.command("init")
def cli_init(
    name: Annotated[str | None, typer.Option("--name", help="Project name.")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing config.")
    ] = False,
) -> None:
    """Initialize ``docs/.helpers/`` in the current project.

    Writes ``docs/.helpers/config.toml`` and ``docs/.helpers/.gitignore``
    under the current working directory. Refuses to clobber an existing
    ``config.toml`` unless ``--force`` is passed; the refuse path surfaces
    as the Phase 1 error envelope (code 1, kind ``cli.not_implemented`` —
    the closest existing fit per ``002.context.md``). The ``.gitignore``
    write is idempotent: identical contents skip the write so mtime stays
    stable.
    """
    project_root: Path = Path.cwd()
    config_path, _gitignore_path, _gitignore_written = write_skeleton(
        project_root, project_name=name, force=force
    )
    # Single-line stdout summary; the JSON shape will be tightened in Phase 7.
    write_result_stdout(f"wrote {config_path.relative_to(project_root).as_posix()}")


@index_app.command("build")
def cli_index_build(
    ctx: typer.Context,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override the walk root for this invocation."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Walk and chunk only; do not write rows.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Per-file timing lines on stderr."),
    ] = False,
) -> None:
    """Build the index for the current project.

    Thin wrapper over :func:`code_index.indexer.build`. Discovers the
    project config via the Phase 1 upward walk for
    ``docs/.helpers/config.toml`` (or honors the global ``--config``
    override); resolves the walk root to ``--root`` when given, else the
    parent of ``docs/.helpers/``; and prints a summary on stdout.

    Under ``--format text`` the summary is the single line
    ``indexed <N> files, <M> chunks``. Under ``--format json`` the summary
    is one JSON object with the :class:`code_index.indexer.IndexerResult`
    fields. ``CodeIndexError`` raised by config discovery or by
    ``indexer.build`` propagates to the Phase 1 envelope handler.
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")
    verbose_flag: bool = bool(verbose or ctx_obj.get("verbose", False))

    config_path: Path = _resolve_config_path(ctx)
    cfg: CodeIndexConfig = load_config(config_path)

    # Project root = parent of `docs/.helpers/`. `--root` overrides only the
    # walk root, not the config-relative project root (matches the indexer's
    # treatment of `root` as the directory to walk).
    walk_root: Path = (
        Path(root).resolve() if root is not None else config_path.parent.parent.parent.resolve()
    )

    result = indexer.build(cfg, walk_root, dry_run=dry_run, verbose=verbose_flag)

    if format_value == "json":
        payload: dict[str, Any] = {
            "files_walked": result.files_walked,
            "files_chunked": result.files_chunked,
            "chunks_inserted": result.chunks_inserted,
            "symbols_inserted": result.symbols_inserted,
            "edges_inserted": result.edges_inserted,
            "seconds_elapsed": result.seconds_elapsed,
        }
        write_json_stdout(payload)
        return

    write_result_stdout(
        f"indexed {result.files_chunked} files, {result.chunks_inserted} chunks"
    )


@index_app.command("sync")
def cli_index_sync(
    ctx: typer.Context,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Per-file lines on stderr."),
    ] = False,
) -> None:
    """Incremental update against the existing index.

    Runs the Phase 6 pre-flight (discover config, verify the index file
    exists, verify ``meta.embed_model`` / ``meta.embed_dim`` match the
    configured backend), calls :func:`code_index.sync.sync`, and writes a
    one-line summary on stdout (or the JSON shape under ``--format json``).
    The boundary handler routes :class:`CodeIndexError` from the pre-flight
    layer through the standard envelope.
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")
    verbose_flag: bool = bool(verbose or ctx_obj.get("verbose", False))

    cfg, project_root, conn, _backend = _preflight(ctx)
    try:
        result = sync_module.sync(cfg, project_root, verbose=verbose_flag)
    finally:
        conn.close()

    if format_value == "json":
        payload: dict[str, Any] = {
            "files_added": result.files_added,
            "files_changed": result.files_changed,
            "files_unchanged": result.files_unchanged,
            "files_removed": result.files_removed,
            "chunks_inserted_total": result.chunks_inserted_total,
            "seconds_elapsed": result.seconds_elapsed,
        }
        write_json_stdout(payload)
        return

    write_result_stdout(
        f"synced: +{result.files_added} ~{result.files_changed} "
        f"={result.files_unchanged} -{result.files_removed} "
        f"({result.chunks_inserted_total} chunks) "
        f"in {result.seconds_elapsed:.2f}s"
    )


@index_app.command("rebuild")
def cli_index_rebuild(
    ctx: typer.Context,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm destructive rebuild.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Per-file lines on stderr."),
    ] = False,
) -> None:
    """Drop and rebuild the index for the current project.

    Thin wrapper over :func:`code_index.indexer.build`. The user-facing
    distinction from ``index build`` is the destructive ``--yes`` gate and
    the absence of ``--root`` / ``--dry-run`` (per ``006/context.md``
    decision 2 and ``002.context.md``). No pre-flight ``embed_model`` /
    ``embed_dim`` check (decision 7): rebuild is the cure for model
    mismatch, and the Phase 4 auto-rebuild drop sequence inside
    :func:`code_index.indexer.build` will overwrite the persisted meta
    keys anyway.

    Without ``--yes`` the command raises :class:`CodeIndexError` with the
    local-string kind ``"usage.confirmation_required"`` (see
    ``002.context.md`` — kept as a raise-site literal rather than promoted
    to :class:`Kinds` pending an architect's decision) and exit code 1.

    Stdout summary matches ``index build``'s shape: ``--format text``
    writes ``indexed <N> files, <M> chunks``; ``--format json`` writes the
    :class:`code_index.indexer.IndexerResult` document.
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")
    verbose_flag: bool = bool(verbose or ctx_obj.get("verbose", False))

    if not yes:
        raise CodeIndexError(
            code=EXIT_USAGE,
            kind="usage.confirmation_required",
            message=(
                "`index rebuild` is destructive; re-run with `--yes` to "
                "confirm dropping and rebuilding the index"
            ),
            detail={"subcommand": "index rebuild"},
        )

    config_path: Path = _resolve_config_path(ctx)
    cfg: CodeIndexConfig = load_config(config_path)
    project_root: Path = config_path.parent.parent.parent.resolve()

    result = indexer.build(
        cfg, project_root, dry_run=False, verbose=verbose_flag
    )

    if format_value == "json":
        payload: dict[str, Any] = {
            "files_walked": result.files_walked,
            "files_chunked": result.files_chunked,
            "chunks_inserted": result.chunks_inserted,
            "symbols_inserted": result.symbols_inserted,
            "edges_inserted": result.edges_inserted,
            "seconds_elapsed": result.seconds_elapsed,
        }
        write_json_stdout(payload)
        return

    write_result_stdout(
        f"indexed {result.files_chunked} files, {result.chunks_inserted} chunks"
    )


class _SearchMode(enum.StrEnum):
    """``--mode`` enum.

    :class:`enum.StrEnum` (Python 3.11+) gives the members native ``str``
    behavior so Typer renders the values as bare strings on ``--help`` and
    accepts the literal ``"bm25"`` / ``"dense"`` / ``"hybrid"`` on the
    command line. Unknown values surface as Typer's native usage error
    (exit code 2). Per ``002.context.md`` this is the recommended path
    over a hand-rolled :data:`Kinds.CONFIG_BAD_ENUM` raise — the
    Typer-level rejection already satisfies the contract.
    """

    bm25 = "bm25"
    dense = "dense"
    hybrid = "hybrid"


@app.command("search")
def cli_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Free-text query string.")],
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Restrict to one canonical language name."),
    ] = None,
    k: Annotated[
        int, typer.Option("--k", min=1, help="Maximum results returned.")
    ] = 20,
    bm25_k: Annotated[
        int,
        typer.Option("--bm25-k", min=1, help="BM25 candidate-pool size before fusion."),
    ] = 100,
    dense_k: Annotated[
        int,
        typer.Option(
            "--dense-k", min=1, help="Dense candidate-pool size before fusion."
        ),
    ] = 100,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Restrict to one chunk-kind value."),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", help="GLOB pattern applied to chunks.path."),
    ] = None,
    mode: Annotated[
        _SearchMode,
        typer.Option("--mode", help="bm25|dense|hybrid", case_sensitive=False),
    ] = _SearchMode.hybrid,
) -> None:
    """Hybrid BM25 + dense retrieval over the per-project index.

    Flag table (full) per ``docs/architecture/cli.md``. ``--format``,
    ``--config``, ``--verbose``, ``--quiet`` ride on the shared app
    callback (Phase 1) and are read off ``ctx.obj``.

    Behavior:

    1. Resolves the config (``--config`` override or upward discovery).
    2. Validates ``--lang`` against the active language registry; unknown
       values raise :class:`CodeIndexError` with
       :attr:`Kinds.CONFIG_UNKNOWN_LANGUAGE` (code 2).
    3. Resolves ``<project_root>/docs/.helpers/index.sqlite``; missing
       index raises :class:`CodeIndexError` with :attr:`Kinds.INDEX_MISSING`
       (code 12) pointing the user at ``code_index init`` and
       ``code_index index build``.
    4. Opens the index via :func:`storage.open_index` with
       ``create_if_missing=False``. Schema-version drift surfaces from
       there as :attr:`Kinds.INDEX_SCHEMA_MISMATCH` (code 10).
    5. For ``--mode dense`` and ``--mode hybrid``, instantiates the
       embedding backend via :func:`embeddings.from_config` and runs
       :func:`storage.verify_index_compat` before search. ``--mode bm25``
       skips both — the embedding backend is never loaded.
    6. Runs :func:`search_module.search` with the parsed filters.
    7. Writes results to stdout: text stanzas under ``--format text``
       (default) or one ``{"results": [...]}`` document under
       ``--format json``. Zero results: empty stdout under text, exactly
       ``{"results": []}`` under JSON.

    :class:`CodeIndexError` raised anywhere in this function propagates to
    the Phase 1 boundary handler — never caught and rewrapped here.
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")
    verbose_flag: bool = bool(ctx_obj.get("verbose", False))

    config_path: Path = _resolve_config_path(ctx)
    cfg: CodeIndexConfig = load_config(config_path)

    if lang is not None:
        known_names: list[str] = active_plugins(cfg).names()
        if lang not in known_names:
            raise CodeIndexError(
                code=EXIT_CONFIG,
                kind=Kinds.CONFIG_UNKNOWN_LANGUAGE,
                message=(
                    f"unknown --lang {lang!r}; "
                    f"known languages: {', '.join(known_names)}"
                ),
                detail={"requested": lang, "known": known_names},
            )

    project_root: Path = config_path.parent.parent.parent.resolve()
    db_path: Path = project_root / "docs" / ".helpers" / "index.sqlite"
    if not db_path.exists():
        raise CodeIndexError(
            code=EXIT_INDEX_MISSING,
            kind=Kinds.INDEX_MISSING,
            message=(
                "no index found at "
                f"{db_path.as_posix()}; "
                "run `code_index init` then `code_index index build`"
            ),
            detail={"path": db_path.as_posix()},
        )

    conn = storage.open_index(
        db_path, create_if_missing=False, check_version=True
    )
    try:
        backend: embeddings.EmbeddingBackend | None = None
        if mode is not _SearchMode.bm25:
            backend = embeddings.from_config(cfg)
            storage.verify_index_compat(conn, backend)

        # ``_SearchMode`` is a :class:`enum.StrEnum`; ``.value`` typechecks
        # as the ``Mode`` literal (the enum's members exactly cover its
        # three values), so no cast is needed.
        results: list[SearchResult] = search_module.search(
            conn,
            query,
            backend=backend,
            mode=mode.value,
            k=k,
            bm25_k=bm25_k,
            dense_k=dense_k,
            filters=SearchFilters(lang=lang, kind=kind, path_glob=path),
        )
    finally:
        conn.close()

    if format_value == "json":
        _write_search_json(results)
    else:
        _write_search_text(results, verbose=verbose_flag)


def _write_search_json(results: list[SearchResult]) -> None:
    """Emit ``{"results": [...]}`` with all nine ``SearchResult`` fields."""
    payload: dict[str, Any] = {
        "results": [
            {
                "path": row.path,
                "start_line": row.start_line,
                "end_line": row.end_line,
                "language": row.language,
                "kind": row.kind,
                "name": row.name,
                "scope": row.scope,
                "excerpt": row.excerpt,
                "score": row.score,
            }
            for row in results
        ]
    }
    write_json_stdout(payload)


def _write_search_text(results: list[SearchResult], *, verbose: bool) -> None:
    """Emit one stanza per result; zero results writes nothing on stdout.

    Stanza shape::

        <path>:<start>-<end>  [<language>] <kind> <name or "">
          score=<float>          # only under --verbose
          <scope>                # only when scope is non-None
          <excerpt indented two spaces>

    Stanzas are separated by a single blank line. Under text mode zero
    results means nothing is written to stdout — the contract from
    ``cli.md`` and ``retrieval.md``.
    """
    if not results:
        return

    stanzas: list[str] = []
    for row in results:
        header: str = (
            f"{row.path}:{row.start_line}-{row.end_line}  "
            f"[{row.language}] {row.kind} {row.name or ''}"
        )
        lines: list[str] = [header]
        if verbose:
            lines.append(f"  score={row.score}")
        if row.scope is not None:
            lines.append(f"  {row.scope}")
        for excerpt_line in row.excerpt.splitlines():
            lines.append(f"  {excerpt_line}")
        stanzas.append("\n".join(lines))

    write_result_stdout("\n\n".join(stanzas))


@symbols_app.command("defs")
def cli_symbols_defs(
    ctx: typer.Context,
    name: str,
    exact: Annotated[
        bool, typer.Option("--exact", help="Match symbol name by exact equality.")
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Restrict to one canonical language name."),
    ] = None,
) -> None:
    """Symbol definitions matching ``name``.

    Runs the Phase 6 pre-flight (discover config, verify the index file
    exists, verify ``meta.embed_model`` / ``meta.embed_dim`` match the
    configured backend) then calls :func:`code_index.symbols.query_symbols`
    with ``kind="def"``. Matching is case-sensitive substring by default;
    ``--exact`` switches to equality. Empty results exit 0 with empty stdout
    (text) or ``[]`` (JSON) — zero results is not an error per ``cli.md``.
    """
    _run_symbols_query(ctx, name, kind="def", exact=exact, language=lang)


@symbols_app.command("refs")
def cli_symbols_refs(
    ctx: typer.Context,
    name: str,
    exact: Annotated[
        bool, typer.Option("--exact", help="Match symbol name by exact equality.")
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Restrict to one canonical language name."),
    ] = None,
) -> None:
    """Symbol references matching ``name``.

    Same surface as ``symbols defs`` with ``kind="ref"``; see that command
    for matching semantics and pre-flight behavior.
    """
    _run_symbols_query(ctx, name, kind="ref", exact=exact, language=lang)


def _run_symbols_query(
    ctx: typer.Context,
    name: str,
    *,
    kind: str,
    exact: bool,
    language: str | None,
) -> None:
    """Shared body of ``symbols defs`` and ``symbols refs``.

    Pre-flight + query + emit. The ``_preflight`` helper returns a connection
    the caller owns; we close it on every code path via ``try`` / ``finally``.
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")

    _cfg, _project_root, conn, _backend = _preflight(ctx)
    try:
        hits: list[symbols_module.SymbolHit] = symbols_module.query_symbols(
            conn, name, kind=kind, exact=exact, language=language
        )
    finally:
        conn.close()

    if format_value == "json":
        _write_symbols_json(hits)
    else:
        _write_symbols_text(hits)


def _write_symbols_json(hits: list[symbols_module.SymbolHit]) -> None:
    """Emit the JSON-array shape pinned in ``context.md`` ("JSON output shapes").

    Each element has exactly the keys ``{path, scope, language, name, line}``;
    an empty result emits ``[]``.
    """
    payload: list[dict[str, Any]] = [
        {
            "path": hit.path,
            "scope": hit.scope,
            "language": hit.language,
            "name": hit.name,
            "line": hit.line,
        }
        for hit in hits
    ]
    write_json_stdout(payload)


def _write_symbols_text(hits: list[symbols_module.SymbolHit]) -> None:
    """One line per hit, empty stdout when ``hits`` is empty.

    Format per ``003.context.md`` ("Text output format")::

        <path>:<line> [<language>] <name>      (scope: <scope>)

    When ``scope`` is ``None`` the trailing parenthesized clause is omitted.
    The exact spacing is not contractual (text is for humans; JSON is the
    stable surface).
    """
    if not hits:
        return
    lines: list[str] = []
    for hit in hits:
        line: str = f"{hit.path}:{hit.line} [{hit.language}] {hit.name}"
        if hit.scope is not None:
            line += f"      (scope: {hit.scope})"
        lines.append(line)
    write_result_stdout("\n".join(lines))


@graph_app.command("callers")
def cli_graph_callers(
    ctx: typer.Context,
    symbol: str,
    exact: Annotated[
        bool, typer.Option("--exact", help="Match dst_name by exact equality.")
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Restrict to one canonical language name."),
    ] = None,
) -> None:
    """Edges whose ``dst_name`` matches ``symbol``.

    Runs the Phase 6 pre-flight (discover config, verify the index file
    exists, verify ``meta.embed_model`` / ``meta.embed_dim`` match the
    configured backend) then calls :func:`code_index.graph.query_callers`.
    Matching is case-sensitive substring by default; ``--exact`` switches to
    equality. The ``symbol`` argument is matched against ``edges.dst_name``
    directly — no resolution to a ``symbols`` row is performed (per
    ``004.context.md`` "Edge resolution is lazy"). Empty results exit 0
    with empty stdout (text) or ``[]`` (JSON).
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")

    _cfg, _project_root, conn, _backend = _preflight(ctx)
    try:
        hits: list[graph_module.CallerHit] = graph_module.query_callers(
            conn, symbol, exact=exact, language=lang
        )
    finally:
        conn.close()

    if format_value == "json":
        _write_callers_json(hits)
    else:
        _write_callers_text(hits)


@graph_app.command("deps")
def cli_graph_deps(
    ctx: typer.Context,
    path: str,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Restrict to one canonical language name."),
    ] = None,
) -> None:
    """Outbound edges from chunks whose ``chunks.path`` equals ``path``.

    Runs the Phase 6 pre-flight (discover config, verify the index file
    exists, verify ``meta.embed_model`` / ``meta.embed_dim`` match the
    configured backend) then calls :func:`code_index.graph.query_deps`.

    Path matching is case-sensitive equality (decision 4 in ``context.md``):
    no substring, no globbing. The path must match exactly; use the
    forward-slash relative path printed by ``index sync`` or stored in
    ``chunks.path``. Unresolved ``dst_name`` values are included in the
    result (the contract allows them). Empty results exit 0 with empty
    stdout (text) or ``[]`` (JSON).
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")

    _cfg, _project_root, conn, _backend = _preflight(ctx)
    try:
        hits: list[graph_module.DepHit] = graph_module.query_deps(
            conn, path, language=lang
        )
    finally:
        conn.close()

    if format_value == "json":
        _write_deps_json(hits)
    else:
        _write_deps_text(hits)


def _write_callers_json(hits: list[graph_module.CallerHit]) -> None:
    """Emit the JSON-array shape pinned in ``context.md`` ("JSON output shapes").

    Each element has exactly the keys
    ``{path, scope, language, start_line, kind, dst_name}``; an empty result
    emits ``[]``.
    """
    payload: list[dict[str, Any]] = [
        {
            "path": hit.path,
            "scope": hit.scope,
            "language": hit.language,
            "start_line": hit.start_line,
            "kind": hit.kind,
            "dst_name": hit.dst_name,
        }
        for hit in hits
    ]
    write_json_stdout(payload)


def _write_callers_text(hits: list[graph_module.CallerHit]) -> None:
    """One line per hit, empty stdout when ``hits`` is empty.

    Format per ``004.graph.md`` ("CLI wrapper behavior")::

        <path>:<start_line> [<language>] -> <dst_name> (<kind>) (scope: <scope>)

    When ``scope`` is ``None`` the trailing parenthesized ``(scope: ...)``
    clause is omitted. The exact spacing is not contractual (text is for
    humans; JSON is the stable surface).
    """
    if not hits:
        return
    lines: list[str] = []
    for hit in hits:
        line: str = (
            f"{hit.path}:{hit.start_line} [{hit.language}] "
            f"-> {hit.dst_name} ({hit.kind})"
        )
        if hit.scope is not None:
            line += f" (scope: {hit.scope})"
        lines.append(line)
    write_result_stdout("\n".join(lines))


def _write_deps_json(hits: list[graph_module.DepHit]) -> None:
    """Emit the JSON-array shape pinned in ``context.md`` ("JSON output shapes").

    Each element has exactly the keys ``{path, kind, dst_name, meta}``; an
    empty result emits ``[]``. ``meta`` is the raw JSON string from the
    column or ``null`` per ``004.context.md``.
    """
    payload: list[dict[str, Any]] = [
        {
            "path": hit.path,
            "kind": hit.kind,
            "dst_name": hit.dst_name,
            "meta": hit.meta,
        }
        for hit in hits
    ]
    write_json_stdout(payload)


def _write_deps_text(hits: list[graph_module.DepHit]) -> None:
    """One line per hit, empty stdout when ``hits`` is empty.

    Format per ``004.graph.md`` ("CLI wrapper behavior")::

        <path> -> <dst_name> (<kind>)

    ``meta`` is intentionally omitted from the human output — per
    ``004.context.md`` the JSON channel is the place to consume ``meta``.
    """
    if not hits:
        return
    lines: list[str] = []
    for hit in hits:
        lines.append(f"{hit.path} -> {hit.dst_name} ({hit.kind})")
    write_result_stdout("\n".join(lines))


# ---------------------------------------------------------------------------
# Real implementation: `config show`.
# ---------------------------------------------------------------------------


def _preflight(
    ctx: typer.Context,
) -> tuple[CodeIndexConfig, Path, sqlite3.Connection, embeddings.EmbeddingBackend]:
    """Run the standard Phase 6 pre-flight for ``index sync`` / ``symbols`` / ``graph``.

    Steps (matching ``006/context.md`` "Cross-cutting constraints"):

    1. Discover the config (``--config`` override or upward walk).
    2. Load the config; resolve the project root and the index path.
    3. If ``docs/.helpers/index.sqlite`` does not exist, raise
       :class:`CodeIndexError` with :attr:`Kinds.INDEX_MISSING` (code 12).
    4. Open the index (no schema-version drift handling here — the
       :func:`storage.open_index` helper raises :attr:`Kinds.INDEX_SCHEMA_MISMATCH`
       on its own).
    5. Construct the embedding backend (native exceptions from
       :func:`embeddings.from_config` propagate per decision 6).
    6. Compare ``meta.embed_model`` and ``meta.embed_dim`` against the
       backend's ``name`` / ``dim``; mismatch raises
       :attr:`Kinds.INDEX_EMBED_MODEL_MISMATCH` or
       :attr:`Kinds.INDEX_EMBED_DIM_MISMATCH` (code 11) with a message
       pointing at ``code_index index rebuild``.

    Returns the tuple ``(config, project_root, conn, backend)``. The caller
    owns closing ``conn``. Steps 003 and 004 will reuse this helper as-is —
    the ``backend`` argument is unused by ``symbols`` / ``graph`` but
    constructing it is cheap once fastembed is cached, and the model/dim
    check requires its ``name`` and ``dim`` anyway.
    """
    config_path: Path = _resolve_config_path(ctx)
    cfg: CodeIndexConfig = load_config(config_path)
    project_root: Path = config_path.parent.parent.parent.resolve()
    db_path: Path = project_root / "docs" / ".helpers" / "index.sqlite"
    if not db_path.exists():
        raise CodeIndexError(
            code=EXIT_INDEX_MISSING,
            kind=Kinds.INDEX_MISSING,
            message=(
                f"no index found at {db_path.as_posix()}; "
                "run `code_index index build`"
            ),
            detail={"path": db_path.as_posix()},
        )

    conn = open_index(db_path)
    try:
        backend = embeddings.from_config(cfg)
        stored_model: str | None = get_meta(conn, "embed_model")
        stored_dim: str | None = get_meta(conn, "embed_dim")
        if stored_model != backend.name:
            raise CodeIndexError(
                code=EXIT_INDEX_MODEL,
                kind=Kinds.INDEX_EMBED_MODEL_MISMATCH,
                message=(
                    f"index built with embed_model={stored_model!r}, "
                    f"config wants {backend.name!r}; "
                    "run `code_index index rebuild`"
                ),
                detail={
                    "stored": stored_model,
                    "configured": backend.name,
                },
            )
        if stored_dim != str(backend.dim):
            raise CodeIndexError(
                code=EXIT_INDEX_MODEL,
                kind=Kinds.INDEX_EMBED_DIM_MISMATCH,
                message=(
                    f"index built with embed_dim={stored_dim!r}, "
                    f"config wants {backend.dim!r}; "
                    "run `code_index index rebuild`"
                ),
                detail={
                    "stored": stored_dim,
                    "configured": str(backend.dim),
                },
            )
    except BaseException:
        conn.close()
        raise

    return cfg, project_root, conn, backend


def _resolve_config_path(ctx: typer.Context) -> Path:
    """Return the config path from ``--config`` or upward discovery.

    Raises :class:`CodeIndexError` with ``kind = index.missing`` (code 12) when
    neither ``--config`` nor :func:`discover_config_path` yields a file. The
    mapping to ``index.missing`` is the planner-resolved choice recorded in
    ``005.context.md`` (no dedicated ``config.not_found`` kind in MVP).
    """
    ctx_obj: dict[str, Any] = ctx.obj or {}
    explicit: Path | None = ctx_obj.get("config")
    if explicit is not None:
        return Path(explicit)
    try:
        return discover_config_path(Path.cwd())
    except CodeIndexError as exc:
        # Re-raise as the documented "no config found" surface.
        raise CodeIndexError(
            code=EXIT_INDEX_MISSING,
            kind=Kinds.INDEX_MISSING,
            message="no docs/.helpers/config.toml found; run `code_index init`",
            detail={"start": str(Path.cwd())},
        ) from exc


def _config_show_payload(cfg: CodeIndexConfig, config_path: Path) -> dict[str, Any]:
    """Build the Phase 1 JSON shape for ``config show`` (see ``005.context.md``).

    Phase 7 will add an ``index`` sibling alongside ``config``; the field set
    here is the stable Phase 1 contract.
    """
    project_root: Path = config_path.parent.parent.parent.resolve()
    resolved_roots: list[str] = [
        str((project_root / r).resolve()) for r in cfg.roots
    ]
    return {
        "config": {
            "version": cfg.version,
            "project": cfg.project,
            "project_root": str(project_root),
            "config_path": str(config_path.resolve()),
            "roots": resolved_roots,
            "ignores": cfg.ignores,
            "languages": cfg.languages,
            "extra_languages": cfg.extra_languages,
            "embed_backend": cfg.embed_backend,
            "embed_model": cfg.embed_model,
            "embed_batch_size": cfg.embed_batch_size,
        }
    }


@config_app.command("show")
def cli_config_show(ctx: typer.Context) -> None:
    """Print the resolved configuration to stdout."""
    ctx_obj: dict[str, Any] = ctx.obj or {}
    format_value: str = ctx_obj.get("format", "text")

    config_path: Path = _resolve_config_path(ctx)
    cfg: CodeIndexConfig = load_config(config_path)
    payload: dict[str, Any] = _config_show_payload(cfg, config_path)

    if format_value == "json":
        write_json_stdout(payload)
        return

    inner: dict[str, Any] = payload["config"]
    lines: list[str] = []
    for key in sorted(inner.keys()):
        value: Any = inner[key]
        if isinstance(value, list):
            items: list[Any] = value  # type: ignore[reportUnknownVariableType]
            rendered: str = "[" + ", ".join(repr(v) for v in items) + "]"
        else:
            rendered = str(value)
        lines.append(f"{key} = {rendered}")
    write_result_stdout("\n".join(lines))


# ---------------------------------------------------------------------------
# Boundary handler.
# ---------------------------------------------------------------------------


def _format_from_argv(argv: list[str]) -> str:
    """Best-effort ``--format`` parse without invoking Typer.

    The handler needs to know whether to emit a JSON envelope before Typer
    has populated ``ctx.obj`` (e.g., when an exception is raised in the
    callback). We scan ``argv`` conservatively and default to ``text`` on
    any ambiguity.
    """
    for index, token in enumerate(argv):
        if token == "--format" and index + 1 < len(argv):
            candidate: str = argv[index + 1]
            if candidate in ("text", "json"):
                return candidate
        elif token.startswith("--format="):
            candidate = token.split("=", 1)[1]
            if candidate in ("text", "json"):
                return candidate
    return "text"


def _handle_known(err: CodeIndexError, format_value: str) -> int:
    """Route a :class:`CodeIndexError` per the table in ``005.context.md``."""
    if format_value == "json":
        write_error_envelope_stdout(err)
        write_error_summary_stderr(err)
    else:
        write_error_summary_stderr(err)
    return err.code


def _handle_unknown(exc: BaseException, format_value: str) -> int:
    """Route any non-:class:`CodeIndexError` exception as ``kind=unknown``."""
    synthetic: CodeIndexError = CodeIndexError(
        code=EXIT_UNKNOWN,
        kind=_UNKNOWN_KIND,
        message=f"unhandled exception: {type(exc).__name__}: {exc}",
        detail={"exception_type": type(exc).__name__},
    )
    if format_value == "json":
        write_error_envelope_stdout(synthetic)
        write_error_summary_stderr(synthetic)
    else:
        write_error_summary_stderr(synthetic)
    return synthetic.code


def _invoke(argv: list[str] | None = None) -> int:
    """Run the Typer app and translate exceptions into exit codes.

    Returns the integer exit code; never raises. ``argv`` is the list of
    arguments (excluding the program name); when ``None`` ``sys.argv[1:]`` is
    used. The Click command is obtained via :func:`typer.main.get_command`
    and invoked directly so the :class:`BoundaryTyper.__call__` wrapper is
    not re-entered.
    """
    if argv is None:
        argv = sys.argv[1:]
    format_value: str = _format_from_argv(argv)
    command: click.BaseCommand = typer.main.get_command(app)
    try:
        # ``standalone_mode=True`` keeps Click's native ``--help`` / usage-error
        # handling (which prints help to stdout and exits via SystemExit), while
        # :class:`CodeIndexError` still bubbles up because Click only intercepts
        # ``ClickException`` / ``Abort`` in this mode.
        command.main(args=argv, prog_name="code_index", standalone_mode=True)
        return 0
    except CodeIndexError as err:
        return _handle_known(err, format_value)
    except SystemExit as exc:
        code: Any = exc.code
        return int(code) if isinstance(code, int) else 0
    except Exception as exc:  # noqa: BLE001 — boundary handler
        return _handle_unknown(exc, format_value)
