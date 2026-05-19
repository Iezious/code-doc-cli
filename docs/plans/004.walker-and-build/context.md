# Feature 004 — walker-and-build

Phase 4 of the MVP. Delivers the file walker, the indexer pipeline, and the two
user-facing subcommands that drive them: `code_index init` and
`code_index index build`. End-to-end definition of done: `init` followed by
`index build` against a polyglot fixture project populates every index table
with the expected rows; ignored and binary files are absent.

This is the first phase where Phases 1, 2, and 3 are composed end-to-end.
Foundations (storage, config, errors, CLI scaffold), the embedding backend,
and the seven language plugins all become load-bearing here.

## Scope envelope

- File walker honoring every rule in
  [`../../architecture/architecture.md`](../../architecture/architecture.md)'s
  "Indexer walking" section.
- Indexer pipeline: walk to plugin dispatch to embedding batching to storage
  inserts, per "Data flow / Index build" in the same doc.
- `code_index init` subcommand body: writes `docs/.helpers/config.toml` (per
  the "What `init` writes" section of
  [`../../architecture/config.md`](../../architecture/config.md)) and
  `docs/.helpers/.gitignore`.
- `code_index index build` subcommand body: flags per
  [`../../architecture/cli.md`](../../architecture/cli.md) — `--root`,
  `--dry-run`, `--verbose`.
- Auto-rebuild semantics for `index build`: when the index already contains
  data rows, those rows are silently dropped before insert. No `--force` flag.
  Schema is preserved; only row data is cleared.

## Out of scope

- `code_index index sync`, `code_index index rebuild` (Phase 6). Their CLI
  stubs from Phase 1 remain unchanged.
- `code_index search`, `code_index symbols`, `code_index graph` (Phases 5/6).
- The `--strict` flag. Deferred entirely; default skip-and-warn behavior only.
  See `outcome.md` for the architect-level note on the cli.md /
  errors-and-exit-codes.md inconsistency this defers.
- Voyage backend (Phase 7). The indexer drives whatever
  `embeddings.from_config(config)` returns; in MVP that is the fastembed
  backend from Phase 2.
- Per-plugin config sub-tables (e.g. OSSL toggle for LSL). Not introduced.
- Embedding cache by content hash. Deferred to v1.1 per
  [`../../architecture/embeddings.md`](../../architecture/embeddings.md).

## Architecture inputs (authoritative)

Read these before any step. The phase introduces no new architectural
decisions; everything below this line is implementation against pinned design.

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) —
  Phase 4 section. DoD is the scope contract.
- [`../../architecture/architecture.md`](../../architecture/architecture.md) —
  "Indexer walking" section is the walker rule set; "Data flow / Index build"
  is the pipeline shape.
- [`../../architecture/cli.md`](../../architecture/cli.md) — `init` and
  `index build` flag tables; output discipline (stdout = results, stderr =
  logs and warnings).
- [`../../architecture/config.md`](../../architecture/config.md) — "What
  `init` writes" pins the skeleton file shape; the schema is what the loader
  built in Phase 1 already validates.
- [`../../architecture/storage.md`](../../architecture/storage.md) — table
  shapes the indexer inserts into; WAL mode; sqlite-vec; FTS5; `meta` keys;
  the `files` table and "Sync state" subsection (the indexer populates
  `files`; Phase 6 reads it).
- [`../../architecture/chunking-and-languages.md`](../../architecture/chunking-and-languages.md) —
  `Chunk` / `Symbol` / `Edge` shapes; `Language` Protocol; per-plugin name and
  edge conventions.
- [`../../architecture/embeddings.md`](../../architecture/embeddings.md) —
  `EmbeddingBackend.encode(texts) -> ndarray (N, D)`; `from_config` factory.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) —
  parsing / IO categories. Phase 4 uses only default mode (skip + warn).

## Prior-phase artifacts this phase consumes

- Phase 1 (`docs/plans/001.foundations/`): config loader, storage open helper
  and migration harness (`0_to_1.py` ran already, creating the six tables
  including `files`), errors module (`CodeIndexError`, exit code constants,
  `write_log_stderr`, JSON envelope writer), CLI scaffold (`typer` app with
  `init` and `index build` stubs).
- Phase 2 (`docs/plans/002.embedding-backend/`): `FastembedBackend`
  implementing the `EmbeddingBackend` protocol; `from_config(config)` factory
  that returns the configured backend (fastembed in MVP).
- Phase 3 (`docs/plans/003.language-plugins/`): `LanguageRegistry` with
  `active_plugins(config)` returning a registry restricted by `config.languages`
  and extended by `config.extra_languages`. Each plugin instance exposes
  `name`, `extensions`, `chunk(path, content)`, `symbols(path, content)`,
  `imports(path, content)`.

## Module layout (flat siblings)

- `src/code_index/walker.py` — new, top-level module. Step 001.
- `src/code_index/indexer.py` — new, top-level module. Step 003.
- `src/code_index/cli.py` — extended by steps 002 and 004 (the stubs become
  real implementations). The `init` body may optionally be factored into a
  small `src/code_index/init.py` helper if step 002 chooses; orchestrator
  approved either form.
- Phase 6's `sync.py` will sit next to these as a third sibling. It will
  read the `files` table this phase populates.

## Cross-cutting constraints

- **Stream discipline (per cli.md).** Results go to stdout. Warnings,
  progress, summary lines go to stderr via the Phase 1 `write_log_stderr` (or
  equivalent) helper. `--format json` still emits one JSON document on stdout.
- **Default error mode (per errors-and-exit-codes.md).** Per-file IO failures
  and plugin raises: skip + emit a stderr warning + continue + exit 0. The
  `--strict` upgrade is deferred to Phase 6.
- **Auto-rebuild semantics (orchestrator-confirmed).** `index build` against
  a populated index silently drops the row data from `chunks`, `chunks_fts`,
  `embeddings`, `symbols`, `edges`, `files`, and resets the `meta` keys the
  indexer owns (`embed_model`, `embed_dim`). `meta.schema_version` is
  preserved. No `--force` flag. The user-facing `index rebuild` subcommand in
  Phase 6 will reuse this same drop path.
- **Schema versioning.** The Phase 1 storage open helper applies migrations
  on open; the indexer assumes the schema is at the current version once the
  helper returns. The indexer never bumps `schema_version` itself.
- **`embed_batch_size`.** The indexer reads this from the config object
  (default 32). Empty input to `backend.encode` is a no-op (Phase 2 backend
  already handles this).

## New dependencies

- `pathspec>=0.12` added to `[project.dependencies]` in step 001 for
  `.gitignore` matching. Hand-rolling git wildmatch is error-prone.

## Test fixtures

- `tests/fixtures/walker/` — small directories exercising individual walker
  rules. Owned by step 001.
- `tests/fixtures/projects/polyglot_minimal/` — the end-to-end DoD fixture.
  Owned by step 004. Contains one source file per supported language, a root
  `.gitignore` listing an `ignored/` directory, files inside `ignored/` that
  must NOT appear in the index, and a `data.bin` binary file (NUL bytes) at
  root that must NOT appear. The fixture is NOT pre-populated with
  `docs/.helpers/`; the DoD test runs `init` first. Fixtures are copied to
  `tmp_path` per test so each test sees a clean tree.
- The fastembed model cache from Phase 2's `tests/.cache/fastembed/` is
  reused. CI does not redownload on normal runs.

## Shared vocabulary

- **WalkedFile** — the walker's output record. Step 001 owns the shape.
- **IndexerResult** — the indexer's return value (counts and timings). Step
  003 owns the shape.
- **Auto-rebuild** — the silent drop-and-rebuild that `index build` performs
  when prior data exists. Clears six row-data tables (`chunks`,
  `chunks_fts`, `embeddings`, `symbols`, `edges`, `files`) and resets two
  `meta` keys (`embed_model`, `embed_dim`).
- **Indexer-owned tables** — the six row-data tables listed above plus the
  two `meta` keys. The indexer owns their content for the duration of a
  build. `meta.schema_version` and `meta.code_index_version` are not in
  this set — they belong to the storage layer.

## Definition of done (phase-level)

- `uv sync --extra dev` succeeds (new dep: `pathspec>=0.12`).
- `uv run pytest` passes, including the integration test in step 004.
- `uv run ruff check` passes.
- `uv run pyright` passes.
- `code_index init` in an empty directory creates
  `docs/.helpers/config.toml` and `docs/.helpers/.gitignore`.
- `code_index index build` against the polyglot fixture populates
  `chunks`, `chunks_fts`, `embeddings`, `symbols`, `edges`, `files`,
  `meta` with the expected rows; `ignored/` and `data.bin` are absent.
- A second `code_index index build` against the same project succeeds and
  the row counts match (auto-rebuild).

## Step map

- **001 walker.md** — `src/code_index/walker.py`. Independent of plugins,
  storage, embeddings. Pure file enumeration.
- **002 init.md** — `code_index init` body in `cli.py`. Independent of the
  walker. Pure file writes.
- **003 indexer-pipeline.md** — `src/code_index/indexer.py`. Composes 001,
  Phase 1 storage, Phase 2 embeddings, Phase 3 plugins.
- **004 index-build-cli.md** — `code_index index build` body in `cli.py`.
  Thin wrapper around step 003. Owns the polyglot fixture and the DoD
  integration test.

Step 001 and step 002 are independent and may be implemented in any order.
Steps 003 and 004 are sequential.
