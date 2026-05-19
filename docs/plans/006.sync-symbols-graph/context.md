# Feature 006 — sync-symbols-graph

Phase 6 of the MVP per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md). Delivers the four remaining MVP read/maintenance subcommands:

1. `code_index index sync` — incremental update via mtime+size comparison against the `files` table.
2. `code_index index rebuild [--yes]` — thin wrapper around `indexer.build` with a user-facing confirmation gate.
3. `code_index symbols defs|refs <name>` — symbol lookup with substring/exact matching and `--lang` filtering.
4. `code_index graph callers <symbol>` and `graph deps <path>` — edge queries with lazy `dst_name` resolution.

Phase 5 (search) is being planned in a parallel session; Phase 6 does **not** depend on Phase 5.

## Scope envelope

Strictly Phase 6's bullets from `mvp-phases.md` plus the DoD. Phase 6 is a **pure consumer** of the existing v1 schema — no migrations, no schema changes.

## Out of scope (per orchestrator briefing)

- Voyage backend (Phase 7).
- `config show` full implementation with index meta (Phase 7; Phase 1's stub remains).
- Cross-subcommand JSON polish (Phase 7).
- `--strict` flag for plugin/IO failures (still unresolved per Phase 4's `outcome.md`; Phase 6 does not introduce it).
- Backend init failure wrapping in `CodeIndexError` (Phase 7). Native exceptions from `embeddings.from_config` propagate to the global `EXIT_UNKNOWN` handler.
- A `--limit` flag on `symbols` / `graph` subcommands (deferred per decision 3 below).
- `code_index doctor` (deferred to v1.1 per `mvp-scope.md`).
- Embedding cache by content hash, per-content-hash sync skip (roadmap).

## Architecture inputs (authoritative)

Read these before any step. Phase 6 introduces no new design decisions.

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) — Phase 6 section. DoD is the scope contract.
- [`../../architecture/cli.md`](../../architecture/cli.md) — `index sync`, `index rebuild`, `symbols`, `graph` flag tables and matching contract.
- [`../../architecture/storage.md`](../../architecture/storage.md) — schema; especially the `files` table, "Sync state" subsection, "Edge resolution" (lazy at query time, `dst_name` join against `symbols.name`), schema versioning, concurrency.
- [`../../architecture/architecture.md`](../../architecture/architecture.md) — "Sync" data-flow section (the 4-step mtime+size algorithm).
- [`../../architecture/chunking-and-languages.md`](../../architecture/chunking-and-languages.md) — symbol identity: case-sensitivity, `scope` field, per-language name conventions.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) — `index.embed_model_mismatch` / `index.embed_dim_mismatch` are the new failure surfaces Phase 6 first raises.

## User-confirmed decisions

1. **Sync algorithm is mtime+size only.** No git. No `--since <ref>` flag. `cli.md` already reflects this; Phase 6 implements exactly what is documented.
2. **`index rebuild --yes` is a thin wrapper around `indexer.build(config, root)`.** Same drop path as `index build` against a populated index. No separate "rebuild" helper. User-facing distinction = `--yes` confirmation gate and absence of `--dry-run`. Rebuild without `--yes` errors with a usage message pointing at `--yes`. `--verbose` supported (forwards to `indexer.build`).
3. **No `--limit` flag on `symbols` or `graph` subcommands in MVP.** `cli.md` does not pin one. Filtering happens via `--lang` and `--exact`. If perf becomes a problem in practice, a later phase adds the flag.
4. **`graph deps <path>` path matching is exact.** Case-sensitive equality against `chunks.path`. The path is interpreted as project-root-relative with forward slashes (the form `indexer.build` writes per the Phase 4 amendment). No globbing, no substring. Empty result is not an error.
5. **Read connections use the existing `open_index` helper.** No new `read_only` flag added in this phase. Each CLI invocation opens its own connection; `storage.md`'s reader-snapshot semantics still hold.
6. **Backend init failures during `index sync` are not wrapped in `CodeIndexError` yet.** Native exceptions propagate to the global `EXIT_UNKNOWN` handler. Polishing this is Phase 7's job. Recorded as a known-rough-edge / Phase-7 cleanup, not new Phase 6 scope.
7. **Index-state mismatch checks.** `index sync` and the four symbols/graph subcommands check stored `meta.embed_model` and `meta.embed_dim` against the configured backend before any other work. Mismatch raises `CodeIndexError` with `Kinds.INDEX_EMBED_MODEL_MISMATCH` (code 11) or `Kinds.INDEX_EMBED_DIM_MISMATCH` (code 11), with a message pointing at `code_index index rebuild`. `index rebuild` itself does **not** perform this check — it is about to drop the data anyway.
8. **Missing index.** If `docs/.helpers/index.sqlite` is absent, all four subcommands error with `Kinds.INDEX_MISSING` (code 12), pointing at `code_index index build`. The Phase 1 config-discovery helper raises the related `INDEX_MISSING` for missing `config.toml`; the index-file-missing case uses the same `kind` with a different `message`.

## Prior-phase artifacts this phase consumes

Phase 6 is a pure consumer of earlier phases. Surfaces below are pinned; do not re-spec them.

### From Phase 1 (`docs/plans/001.foundations/`)

- `code_index.errors`:
  - `CodeIndexError(code: int, kind: str, message: str, detail: dict | None = None)`.
  - Exit-code constants: `EXIT_OK`, `EXIT_USAGE`, `EXIT_CONFIG`, `EXIT_INDEX_SCHEMA`, `EXIT_INDEX_MODEL`, `EXIT_INDEX_MISSING`, `EXIT_BACKEND`, `EXIT_UNKNOWN`, etc.
  - Kinds registry: `Kinds.INDEX_MISSING = "index.missing"`, `Kinds.INDEX_SCHEMA_MISMATCH = "index.schema_mismatch"`, `Kinds.INDEX_EMBED_MODEL_MISMATCH = "index.embed_model_mismatch"`, `Kinds.INDEX_EMBED_DIM_MISMATCH = "index.embed_dim_mismatch"`, `Kinds.CLI_NOT_IMPLEMENTED = "cli.not_implemented"`.
  - Stream writers: `write_result_stdout`, `write_log_stderr`, `write_error_envelope_stdout`, `write_error_summary_stderr`.
- `code_index.config`:
  - `load_config(config_path, *, project_root=None, engine_version=None) -> CodeIndexConfig`.
  - Config discovery helper (Phase 1's `discover_config_path` or equivalent — referenced by the CLI wrapper).
- `code_index.storage`:
  - `open_index(db_path, *, create_if_missing=True, check_version=True) -> sqlite3.Connection`.
  - `get_meta(conn, key) -> str | None`; `set_meta(conn, key, value) -> None`.
  - `CURRENT_SCHEMA_VERSION = "1"`.
- `code_index.cli`:
  - Typer app with sub-typers `index_app`, `symbols_app`, `graph_app`.
  - Phase 6 subcommands (`index_app.command("sync")`, `index_app.command("rebuild")`, `symbols_app.command("defs")`, `symbols_app.command("refs")`, `graph_app.command("callers")`, `graph_app.command("deps")`) currently exist as **stubs** raising `CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, …)`. Phase 6 replaces the stub bodies.
  - Global flags `--config`, `--format`, `--verbose`, `--quiet` live on the app callback and are stored on `typer.Context.obj`; subcommands read them from there.
  - Error-envelope handler / decorator pattern used by `config show` is the canonical CLI wrapper — reuse it. Boundary handler catches `CodeIndexError` and routes through `write_error_envelope_stdout` / `write_error_summary_stderr` then `raise typer.Exit(err.code)`.

### From Phase 2 (`docs/plans/002.embedding-backend/`)

- `code_index.embeddings.EmbeddingBackend` Protocol with `name: str`, `dim: int`, `encode(texts: list[str]) -> np.ndarray`.
- `code_index.embeddings.from_config(config) -> EmbeddingBackend`.
- Backend init failures from `from_config` are not yet wrapped in `CodeIndexError` (Phase 7 cleanup); Phase 6 lets them propagate (decision 6).

### From Phase 3 (`docs/plans/003.language-plugins/`)

- `LanguageRegistry.for_extension(ext) -> Language | None`.
- `active_plugins(config) -> LanguageRegistry`.
- Frozen dataclasses `Chunk`, `Symbol`, `Edge`. `Symbol` has **no** `scope` field; `scope` lives on `Chunk`. To surface `scope` in `symbols defs|refs`, Phase 6 joins `symbols` → `chunks` via `chunk_id`.

### From Phase 4 (`docs/plans/004.walker-and-build/`)

- `code_index.walker.WalkedFile` (frozen) with `path: Path`, `rel_path: Path`, `content: str`, `extension: str`, `decode_warning: bool`.
- `code_index.walker.walk(root, config) -> Iterator[WalkedFile]`.
- `code_index.indexer.build(config, root, *, dry_run=False, verbose=False) -> IndexerResult`.
- `indexer.build` populates `files` via per-row upsert after each file is fully chunked / embedded / symbol+edge-inserted. Files that fail (plugin raise, IO error) get no `files` row.
- Auto-rebuild drop sequence (already in Phase 4):
  ```sql
  DELETE FROM edges;
  DELETE FROM symbols;
  DELETE FROM embeddings;
  DELETE FROM chunks_fts;
  DELETE FROM chunks;
  DELETE FROM files;
  DELETE FROM meta WHERE key IN ('embed_model', 'embed_dim');
  ```
  `meta.schema_version` is untouched.
- Polyglot fixture at `tests/fixtures/projects/polyglot_minimal/`. Phase 6's DoD test reuses it.

## Sync algorithm spec

The exact algorithm `code_index index sync` implements:

1. Walk the project root using `walker.walk(root, config)`. Collect the set of walked paths as a dict keyed by the forward-slashed, project-root-relative path (the same form `chunks.path` and `files.path` use).
2. Open a write connection via `open_index`. Read all `files` rows into an in-memory map `{path: (mtime, size)}`.
3. For each walked file:
   - **New** (path not in the map): chunk, embed, insert into `chunks` / `chunks_fts` / `embeddings` / `symbols` / `edges`, upsert into `files`. Same code path the indexer uses per file.
   - **Changed** (path in map AND (mtime differs OR size differs)): call `delete_file_rows(conn, path)`, then re-chunk / re-embed / insert as for "new". Upsert `files` (mtime/size now match disk).
   - **Unchanged** (path in map AND mtime+size match): no action.
4. After processing the walked set, for each `path` in the map but not in the walked set: call `delete_file_rows(conn, path)` (which also removes the `files` row).
5. Emit a summary to stdout: counts of `files_added`, `files_changed`, `files_unchanged`, `files_removed`, `chunks_inserted_total`, `seconds_elapsed`.

### Per-file delete helper

Owned by Phase 6, lives in `src/code_index/sync.py` next to the sync logic (not in `indexer.py`).

```python
def delete_file_rows(conn: sqlite3.Connection, path: str) -> None:
    """Delete all rows for a single file from chunks, chunks_fts, embeddings,
    symbols, edges, and files. Order matters: dependent tables before chunks;
    finally files."""
```

SQL sequence (inside one transaction per file):

```sql
DELETE FROM edges       WHERE src_chunk_id IN (SELECT id FROM chunks WHERE path = ?);
DELETE FROM symbols     WHERE chunk_id    IN (SELECT id FROM chunks WHERE path = ?);
DELETE FROM embeddings  WHERE chunk_id    IN (SELECT id FROM chunks WHERE path = ?);
DELETE FROM chunks_fts  WHERE rowid       IN (SELECT id FROM chunks WHERE path = ?);
DELETE FROM chunks      WHERE path = ?;
DELETE FROM files       WHERE path = ?;
```

The coder may collapse repeated subqueries into a CTE; either form is acceptable as long as the resulting row set is the same.

## Symbols / graph SQL contract

Read [`../../architecture/cli.md`](../../architecture/cli.md) for the prose contract. Translation to SQL:

### `symbols defs <name>`

```sql
SELECT chunks.path, chunks.scope, chunks.language, symbols.name, symbols.line
FROM symbols
JOIN chunks ON symbols.chunk_id = chunks.id
WHERE symbols.kind = 'def'
  AND symbols.name LIKE ?              -- '%<name>%' default, '<name>' under --exact
  [AND chunks.language = ?]            -- only when --lang is supplied
ORDER BY chunks.path, symbols.line;
```

### `symbols refs <name>`

Same as `defs` with `symbols.kind = 'ref'`.

### `graph callers <symbol>`

```sql
SELECT chunks.path, chunks.scope, chunks.language, chunks.start_line,
       edges.kind, edges.dst_name
FROM edges
JOIN chunks ON edges.src_chunk_id = chunks.id
WHERE edges.dst_name LIKE ?            -- substring default, exact under --exact
  [AND chunks.language = ?]
ORDER BY chunks.path, chunks.start_line;
```

### `graph deps <path>`

```sql
SELECT chunks.path, edges.kind, edges.dst_name, edges.meta
FROM edges
JOIN chunks ON edges.src_chunk_id = chunks.id
WHERE chunks.path = ?                  -- exact, case-sensitive (decision 4)
  [AND chunks.language = ?]
ORDER BY chunks.path, edges.kind, edges.dst_name;
```

Results include both resolved and unresolved `dst_name` values — the contract allows unresolved (per [`../../architecture/storage.md`](../../architecture/storage.md)'s "Edge resolution").

### Matching parameters

- Substring (default): the CLI binds the LIKE parameter as `f"%{name}%"`.
- `--exact`: the CLI binds the raw `name` against `=` (or against LIKE with no wildcards — coder's call; functionally equivalent given case-sensitivity).
- Case-sensitive throughout (SQLite LIKE is case-insensitive for ASCII by default; switch to GLOB or use `LIKE ... ESCAPE` with the appropriate PRAGMA, or apply `PRAGMA case_sensitive_like = ON;` on the read connection — coder picks). The Phase 6 step files pin one approach; whichever it is must be documented in the step's `<SSS>.context.md`.

## JSON output shapes

Each subcommand's `--format json` shape is fixed from day one (Phase 7 only polishes wording — it does not redesign shape). Each shape is a single JSON document on stdout.

### `index sync`

```json
{
  "files_added": 0,
  "files_changed": 0,
  "files_unchanged": 0,
  "files_removed": 0,
  "chunks_inserted_total": 0,
  "seconds_elapsed": 0.0
}
```

### `index rebuild`

Reuses `index build`'s JSON shape (Phase 4):

```json
{
  "files_walked": 0,
  "files_chunked": 0,
  "chunks_inserted": 0,
  "symbols_inserted": 0,
  "edges_inserted": 0,
  "seconds_elapsed": 0.0
}
```

### `symbols defs` / `symbols refs`

JSON array of objects:

```json
[
  {"path": "src/foo.py", "scope": "foo.Bar", "language": "python", "name": "baz", "line": 12}
]
```

### `graph callers`

```json
[
  {"path": "src/foo.py", "scope": "foo", "language": "python", "start_line": 1, "kind": "call", "dst_name": "bar"}
]
```

### `graph deps`

```json
[
  {"path": "src/foo.py", "kind": "import", "dst_name": "os", "meta": null}
]
```

`meta` is the raw string written by the indexer (JSON string or `null`). Phase 6 does not re-parse it; Phase 7's JSON polish may.

## Module layout

- `src/code_index/sync.py` — **new.** Owns `delete_file_rows` and the `sync(...)` engine entry point. Sibling of `walker.py` and `indexer.py`.
- `src/code_index/symbols.py` — **new.** Pure query layer; exposes a small Python API the CLI calls.
- `src/code_index/graph.py` — **new.** Pure query layer.
- `src/code_index/cli.py` — **edit.** Replace six stubs (`index sync`, `index rebuild`, `symbols defs`, `symbols refs`, `graph callers`, `graph deps`) with real implementations.

## Cross-cutting constraints

- **Stream discipline (per `cli.md`).** Results to stdout; warnings, progress, summary lines to stderr via the Phase 1 `write_log_stderr` (or equivalent). `--format json` emits one JSON document on stdout.
- **No bare `print`.** Only the Phase 1 sanctioned writers in `errors.py`.
- **Forward-slash paths** everywhere a path appears in DB, JSON, or stderr text.
- **Connection lifecycle.** One open connection per CLI invocation. The boundary handler closes it on `CodeIndexError` (or `finally`).
- **Pre-flight checks.** Every Phase 6 subcommand except `index rebuild` runs:
  1. Discover config (Phase 1 helper).
  2. Open index via `open_index(...)`. If the file does not exist, raise `CodeIndexError(EXIT_INDEX_MISSING, Kinds.INDEX_MISSING, "no index found at <path>; run `code_index index build`")`. (Concretely: check `db_path.exists()` before calling `open_index` since `open_index` would otherwise auto-create.)
  3. Read `meta.embed_model` and `meta.embed_dim`. Compare against the configured backend's `name` and `dim`. Mismatch raises `INDEX_EMBED_MODEL_MISMATCH` or `INDEX_EMBED_DIM_MISMATCH` (code 11).
  - `index rebuild` skips both checks: it is about to drop the rows.
- **Schema versioning.** `open_index` already validates `meta.schema_version`; no Phase 6 code does this explicitly.

## Shared vocabulary

- **SyncResult** — the engine's return value from `sync.sync(...)`. Counts and timings used by both the CLI wrapper and tests.
- **`delete_file_rows`** — per-file row deletion helper in `sync.py`. Owned by Phase 6; not in `indexer.py`.
- **Pre-flight check** — the three-step sequence above (discover config, open index, verify embed_model/embed_dim) shared by `index sync`, `symbols`, and `graph`.
- **"Forward-slash relative path"** — the on-disk path of a source file rendered with `Path.as_posix()` and relative to the project root, matching what `indexer.build` writes to `chunks.path` and `files.path`. This is the canonical path string everywhere in Phase 6.

## Dependency direction

```
001 sync-engine ─┐
                 │
002 rebuild-cli  ├── 005 dod-integration
                 │
003 symbols ─────┤
                 │
004 graph ───────┘
```

001, 002, 003, 004 are mutually independent and may be implemented in parallel. 005 depends on all four.

## Definition of done (phase-level, verbatim from `mvp-phases.md`)

> Edit one fixture file, run `code_index index sync`, verify only that file's rows changed; `code_index symbols defs <name>` returns expected hits with the right `scope`; `code_index graph callers <symbol>` returns the expected source chunks; `code_index graph deps <path>` returns expected target names, including any unresolved ones (the contract allows them).

Operationalized as step 005 (`tests/test_phase6_dod.py`):

1. Copy `tests/fixtures/projects/polyglot_minimal/` to `tmp_path`.
2. Run `code_index init` then `code_index index build`.
3. Modify one source file (e.g. add a function to `main.py`).
4. Run `code_index index sync`.
5. Assert: only `main.py`'s rows changed (compare row IDs / counts; other files' `chunks.id` values are untouched).
6. Run `symbols defs <name>` for a name known to exist in the fixture; assert expected hits with the right `scope`.
7. Run `graph callers <symbol>`; assert expected source chunks.
8. Run `graph deps <path>`; assert expected target names (resolved and unresolved).
9. Run `code_index index rebuild --yes`; assert full populate of all six row-data tables and `files`.

## Build and test commands

Per root `CLAUDE.md`:

- `uv sync --extra dev` — install dev environment.
- `uv run pytest` — run tests.
- `uv run ruff check` — lint.
- `uv run ruff format` — format.
- `uv run pyright` — typecheck.

The verifier reads these from root `CLAUDE.md`; do not duplicate command lines in step files unless the step has a non-standard invocation.
