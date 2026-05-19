# Feature 005 — search

Phase 5 of the MVP per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md).
Delivers the `code_index search` subcommand: a hybrid BM25 + dense retrieval
pipeline over the SQLite index produced by Phase 4, with `--mode` switching
between `bm25`, `dense`, and the default `hybrid`, and filters (`--lang`,
`--kind`, `--path`) applied to both pools before RRF fusion.

This is the first phase where the index produced by Phase 4 is read back. The
embedding backend from Phase 2 is reused to embed the query string.

## Scope envelope

- One new module owning the query pipeline: `src/code_index/search.py`, a flat
  sibling of `walker.py` and `indexer.py` (matching the Phase 4 layout).
- BM25 query path against `chunks_fts` (FTS5), returning candidate
  `(chunk_id, rank)` pairs up to `--bm25-k`.
- Dense query path against `embeddings` (`sqlite-vec` cosine), returning
  candidate `(chunk_id, rank)` pairs up to `--dense-k`. Query string is
  embedded with `from_config(config).encode([query])[0]`.
- Filter application **before fusion** to both candidate pools. Filters:
  `--lang` (matches `chunks.language`), `--kind` (matches `chunks.kind`),
  `--path` (glob against `chunks.path`). Applied as SQL `WHERE` clauses on the
  respective candidate queries.
- RRF fusion with `k = 60` (fixed; not configurable). Tie-break by rank in the
  dense list.
- Mode selection: `--mode bm25` skips dense (and skips loading the embedding
  backend); `--mode dense` skips BM25; `--mode hybrid` runs both and fuses.
  Default `hybrid`.
- Result row shape: `path`, `start_line`, `end_line`, `language`, `kind`,
  `name`, `scope`, `excerpt` (first ~30 lines of `chunks.content`), `score`
  (fused RRF score, or the contribution from the single pool under
  single-mode runs).
- `code_index search` subcommand body: replaces the Phase 1 stub. Owns the
  full flag declaration (`--lang`, `--k`, `--bm25-k`, `--dense-k`, `--kind`,
  `--path`, `--mode`) per [`../../architecture/cli.md`](../../architecture/cli.md).
  `--format` is on the shared app callback (Phase 1), not local.
- Text-format output: one stanza per result with a `path:start-end` header
  followed by the excerpt. JSON-format output: a single document
  `{"results": [...]}` on stdout.
- Embedding-compatibility check before search: verify `meta.embed_model` and
  `meta.embed_dim` match the configured backend's `name` and `dim`. Mismatch
  raises `CodeIndexError` (code 11) with the appropriate kind
  (`index.embed_model_mismatch` or `index.embed_dim_mismatch`). The helper
  lives in `code_index.storage` so Phase 6 (symbols/graph) can reuse it.
- Unit tests against a small synthetic SQLite DB with a patched embedding
  backend (no real model download).
- Integration test reproducing the Phase 5 DoD against the Phase 4 polyglot
  fixture.

## Out of scope

- `code_index symbols`, `code_index graph` (Phase 6). Their Phase 1 stubs
  remain unchanged.
- `code_index index sync`, `code_index index rebuild` (Phase 6).
- `code_index config show` real body with index meta, Voyage backend, full
  `--format json` polish across all subcommands (Phase 7).
- Reranker, score-normalized blending, learned-to-rank — explicitly rejected
  in [`../../architecture/retrieval.md`](../../architecture/retrieval.md).
- Watch mode, `--explain` flag — deferred to roadmap per
  [`../../architecture/cli.md`](../../architecture/cli.md) Open questions.
- Changes to Phases 1–4 modules beyond the one storage helper addition. In
  particular: no changes to `errors.py`, `config.py`, `embeddings/`,
  `languages/`, `walker.py`, `indexer.py`.

## Architecture inputs (authoritative)

Read these before any step. Phase 5 introduces no new architectural
decisions; everything below this line is implementation against pinned design.

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) —
  Phase 5 section. DoD is the contract.
- [`../../architecture/retrieval.md`](../../architecture/retrieval.md) —
  hybrid pipeline, RRF formula (`k = 60` fixed, not configurable), candidate
  pool sizes, latency budget, filter-on-both-pools rule, output row shape.
- [`../../architecture/cli.md`](../../architecture/cli.md) — `search` flag
  table, stream discipline (stdout = results, stderr = logs), output
  discipline (one stanza per result, `path:line` prefixed).
- [`../../architecture/storage.md`](../../architecture/storage.md) — schema,
  WAL mode, reader-snapshot semantics, loud-fail stance on schema and model
  drift.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) —
  codes 10 (`index.schema_mismatch`), 11 (`index.embed_dim_mismatch`,
  `index.embed_model_mismatch`), 12 (`index.missing`), 20
  (`backend.encode_failed`), JSON envelope shape.
- [`../../architecture/chunking-and-languages.md`](../../architecture/chunking-and-languages.md) —
  canonical language-name set used by `--lang` validation.

## Prior-phase artifacts this phase consumes

- Phase 1 (`docs/plans/001.foundations/`):
  - `code_index.storage.open_index(db_path, *, create_if_missing=True, check_version=True) -> sqlite3.Connection`
    — search calls this with `create_if_missing=False`. Per
    [`../001.foundations/004.storage.md`](../001.foundations/004.storage.md),
    `open_index` does not itself raise `index.missing` for an absent file
    (it would create one when `create_if_missing=True`, and would surface a
    `sqlite3` error otherwise). The CLI wrapper in step 002 explicitly
    checks `db_path.exists()` first and raises `CodeIndexError(EXIT_INDEX_MISSING, Kinds.INDEX_MISSING, ...)`
    when the file is absent, pointing at `code_index init` + `index build`.
  - `code_index.storage.get_meta(conn, key) -> str | None` — used to read
    `embed_model` and `embed_dim` for the compatibility check.
  - `code_index.config.CodeIndexConfig` (Pydantic) with `languages`,
    `embed_model`, `embed_backend`, etc.; `load_config(path)` +
    `discover_config_path(cwd)` / equivalent from Phase 1.
  - `code_index.errors` — `CodeIndexError`, `Kinds` constants
    (`INDEX_MISSING`, `INDEX_EMBED_MODEL_MISMATCH`,
    `INDEX_EMBED_DIM_MISMATCH`, `INDEX_SCHEMA_MISMATCH`), exit-code
    constants (`EXIT_INDEX_MISSING`, `EXIT_INDEX_MODEL`,
    `EXIT_INDEX_SCHEMA`), `write_result_stdout`, `write_log_stderr`,
    `write_error_envelope_stdout`, `write_error_summary_stderr`. The
    same boundary exception handler from Phase 1's `cli.py` is reused.
  - `code_index.cli` — Phase 1 stub for `search`:
    `cli_search(query: str, ...)` registered on the Typer app. Phase 5
    replaces the body and owns the full flag declaration. `--format`
    stays on the shared app callback.
- Phase 2 (`docs/plans/002.embedding-backend/`):
  - `EmbeddingBackend` Protocol with `encode(texts: list[str]) -> np.ndarray`
    and attrs `name: str`, `dim: int`.
  - `code_index.embeddings.from_config(config) -> EmbeddingBackend` factory.
    Search instantiates it once per CLI invocation. The query string is
    embedded with one `encode` call.
- Phase 3 (`docs/plans/003.language-plugins/`):
  - `code_index.languages.registry.LanguageRegistry.names() -> list[str]`
    returns plugin names (canonical values used in `chunks.language`). Used
    for `--lang` validation. Canonical names match `chunks.language`
    directly; no alias map.
- Phase 4 (`docs/plans/004.walker-and-build/`):
  - The polyglot fixture `tests/fixtures/projects/polyglot_minimal/` exists
    by Phase 5 time. The Phase 5 end-to-end DoD test reuses it (runs
    `code_index init` + `code_index index build` in setup, then exercises
    `search`).
  - `code_index.indexer` populates `chunks`, `chunks_fts`, `embeddings`,
    `symbols`, `edges`, `meta` with the row shapes Phase 5 queries.

## Module layout (flat siblings)

- `src/code_index/search.py` — new, top-level module. Step 001.
- `src/code_index/storage/__init__.py` — extended in step 001 with the
  embedding-compatibility helper (see "Cross-cutting constraints" below).
- `src/code_index/cli.py` — extended by step 002 (the Phase 1 `search` stub
  becomes the real implementation).

## Cross-cutting constraints

- **Stream discipline (per `cli.md`).** Results to stdout (text stanzas or
  one JSON document under `--format json`); warnings/timings/progress to
  stderr via the Phase 1 helpers. Subcommand code never calls `print`.
- **Zero-results is not an error.** `search` returning no rows exits 0.
  Under `--format text` it prints nothing on stdout; under `--format json`
  it prints exactly `{"results": []}`.
- **RRF `k` is fixed at 60.** Pinned as `RRF_K = 60` in `search.py`. Not
  exposed in config; not exposed as a flag. Architecture explicitly
  forbids it.
- **Pool-size flags are positive ints only.** `--bm25-k` and `--dense-k`
  are validated for `>= 1`; no upper bound beyond the SQL engine's natural
  limit. Per `retrieval.md`, agents tune for recall.
- **Filter-on-both-pools rule.** `--lang`, `--kind`, `--path` are applied
  to both the BM25 and the dense candidate queries via SQL `WHERE`,
  before fusion. Filters are never applied post-fusion.
- **Loud failure on index/model drift.** Schema-version mismatch is
  surfaced by `open_index` (code 10). Embedding model/dim drift is
  surfaced by the new storage helper before any query runs (code 11).
- **Storage helper placement (planner decision).** The
  embedding-compatibility check lives in `code_index.storage`
  (`verify_index_compat`), not inline in `search.py`. Phase 6's
  symbols and graph subcommands will reuse it. This addition is recorded
  in [`outcome.md`](outcome.md) for the architect to fold into
  `storage.md`.
- **`--mode bm25` skips backend load.** When mode is `bm25`, the
  embedding backend is not instantiated and the compatibility check is
  skipped (since no dense query runs and the backend is the only side
  of the mismatch contract). When mode is `dense` or `hybrid`, the
  backend is instantiated and the compatibility check runs.
- **`--lang` validation against the registry.** `--lang` values are
  checked against `LanguageRegistry.from_builtins().names()` plus the
  configured `extra_languages` (resolved via `active_plugins(config)`).
  An unknown name raises `CodeIndexError(EXIT_CONFIG,
  Kinds.CONFIG_UNKNOWN_LANGUAGE, ...)`.
- **No emojis, no HTML; forward slashes** in any path strings in tests
  or docs.

## Shared vocabulary

- **`RRF_K`** — the fixed RRF constant `60`, defined as a module-level
  `Final[int]` in `search.py`.
- **`SearchResult`** — the result-row dataclass, owned by `search.py`.
  Fields: `path: str`, `start_line: int`, `end_line: int`,
  `language: str`, `kind: str`, `name: str | None`, `scope: str | None`,
  `excerpt: str`, `score: float`. Frozen dataclass.
- **Candidate pool** — the per-mode pre-fusion list of `(chunk_id, rank)`
  pairs. Capped at `--bm25-k` or `--dense-k`.
- **Mode** — `"bm25" | "dense" | "hybrid"`. The string literal also drives
  Typer's enum validation in step 002.
- **Excerpt length** — first 30 lines of `chunks.content` (defined as a
  module-level `EXCERPT_MAX_LINES: Final[int] = 30` in `search.py`).
  Matches the "default ~30 lines" guidance in `retrieval.md`.
- **`verify_index_compat`** — the new storage helper that validates
  `meta.embed_model` and `meta.embed_dim` against a backend, raising
  `index.embed_model_mismatch` (code 11) or `index.embed_dim_mismatch`
  (code 11).

## Phase 5 DoD (the contract)

Per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md):

- `uv sync --extra dev` succeeds (no new mandatory deps).
- `uv run pytest` passes, including the unit tests in step 001 and the
  integration test in step 002.
- `uv run ruff check` passes.
- `uv run pyright` passes.
- Against the Phase 4 polyglot fixture (built via `code_index init` +
  `code_index index build` in test setup):
  - A known symbol-name query (e.g. a function name appearing in one of
    the fixture sources) returns a result whose `path:start_line` matches
    the expected location.
  - A known conceptual query (a natural-language description present in a
    docstring or comment) returns the expected chunk.
  - `--mode bm25` returns a single-pool result list (no dense
    contribution).
  - `--mode dense` returns a single-pool result list (no BM25
    contribution).
  - `--mode hybrid` (default) returns a fused list.
- `--format json` round-trips through `json.loads` for both success and
  zero-result cases.

## Step map

- **001 query-pipeline.md** — `src/code_index/search.py` plus the
  `verify_index_compat` extension to `code_index.storage`. Pure-Python
  retrieval module; unit tests with a synthetic SQLite DB and a patched
  embedding backend.
- **002 search-cli.md** — `code_index search` body in `cli.py`,
  text/JSON formatting, and the E2E integration test against the Phase 4
  polyglot fixture (the Phase 5 DoD).

Step 002 depends on step 001. Steps are sequential.

## Open questions

None pinned at planning time. The single planner-resolved choice
(`verify_index_compat` placement in `storage` vs inline in `search.py`)
is recorded under "Cross-cutting constraints" and in
[`outcome.md`](outcome.md).
