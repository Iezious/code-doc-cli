# MVP phases

## Decision

The MVP is built in **seven sequential phases**, foundations-first. Each phase corresponds to one future `/planner` invocation that produces a `docs/plans/<NNN>.<feature>/` folder. Phases are sequential — every phase depends on artifacts from earlier ones — but steps *within* a phase may be planned and dispatched in parallel where the planner judges it safe (notably the seven independent language plugins in Phase 3).

This doc records *how the MVP gets built*. It introduces no new design decisions; it sequences the ones already pinned in [mvp-scope](mvp-scope.md) and the rest of `docs/architecture/`.

## Rationale

- **Foundations first** keeps the dependency direction clean. Storage, config, and errors are infrastructure every later phase consumes; getting them wrong is expensive once features pile on top.
- **One phase = one planner invocation** keeps the planning loop honest. Each phase has a single owner, a single review cycle, and a single status file under `docs/plans/`.
- **The phase boundary is the integration test boundary.** Each phase ends in a runnable Definition of Done that exercises the phase end-to-end against earlier phases' artifacts. Foundation drift surfaces at the next phase boundary instead of at the end of MVP.

## Rejected alternatives

- **Vertical thin slice first** — one language, end-to-end, before broadening. Produces the earliest demo, but every later language stresses the foundations after the foundations have already shipped. The rework risk is real and asymmetric: foundation changes ripple through everything above.
- **High-risk plugins first** — F# and LSL hand-rolled parsers before the tree-sitter ones. Proves the plugin interface against the worst cases up front, but delays anything that looks like "it works" for too long; the planner-explorer pipeline cannot exercise the engine until search is alive.
- **No phasing — a single-shot MVP plan.** Becomes one enormous plan file with no internal verification gates. The whole MVP is either "shipping" or "broken" with nothing in between, and there is no natural point at which the user can intervene without losing context.

## The phases

### Phase 1 — Foundations

- **Delivers:**
  - Python package skeleton under `src/code_index/` (per project root `CLAUDE.md`).
  - `pyproject.toml` set up for `uv tool install --editable .`.
  - Storage layer: SQLite open helper, `sqlite-vec` extension load, FTS5 availability check, schema creation, `meta` table with `schema_version` written at create time, and a forward-only file-per-step migrations harness skeleton.
  - Config loader: TOML parse, full validation per [config](config.md), version-pin check, mapping of every failure to the correct `code` / `kind` from [errors-and-exit-codes](errors-and-exit-codes.md).
  - Errors infrastructure: exit-code constants, `kind` string registry, JSON envelope writer, stderr formatting helpers, and stream-discipline helpers ensuring stdout-results vs stderr-logs separation per [cli](cli.md).
  - CLI scaffold: `typer` entry point with no-op subcommand stubs for every MVP subcommand named in [cli](cli.md), shared flags wired (`--config`, `--format`, `--verbose`, `--quiet`).
- **Depends on:** none.
- **Exercises:** [storage](storage.md), [config](config.md), [errors-and-exit-codes](errors-and-exit-codes.md), [cli](cli.md), [tool-and-data-split](tool-and-data-split.md).
- **DoD:** `uv tool install --editable .` succeeds; `code_index --help` lists every MVP subcommand; `code_index config show --config <path>` validates a hand-written `config.toml`, prints resolved values to stdout, and exits 0; deliberately broken configs exit with the correct code / `kind` from [errors-and-exit-codes](errors-and-exit-codes.md).

### Phase 2 — Embedding backend

- **Delivers:**
  - `EmbeddingBackend` protocol per [embeddings](embeddings.md).
  - `fastembed` implementation using Jina v2 base code (768-dim, CPU).
  - Batching loop honoring `embed_batch_size` from config (default 16).
  - Backend factory that instantiates from config.
- **Depends on:** Phase 1.
- **Exercises:** [embeddings](embeddings.md).
- **DoD:** a unit test calls `backend.encode(["foo", "bar"])` and gets back an `ndarray` of shape `(2, 768)` with `backend.dim == 768`; first-run model download caches under user home; second run reuses the cache.

### Phase 3 — Plugin interface and seven languages

- **Delivers:**
  - Shared dataclasses `Chunk`, `Symbol`, `Edge` per [chunking-and-languages](chunking-and-languages.md).
  - `Language` protocol per [chunking-and-languages](chunking-and-languages.md).
  - Plugin registry with extension dispatch and `extra_languages` loading per [config](config.md).
  - Seven built-in plugins: Python (stdlib `ast`), C# / JavaScript / TypeScript / Go (tree-sitter via `tree-sitter-language-pack`), F# (regex + `.fsproj` reading), LSL (regex / state machine).
  - Per-plugin name and edge conventions per the "Per-language plugins" and "Symbol identity" sections of [chunking-and-languages](chunking-and-languages.md).
- **Depends on:** Phase 1.
- **Exercises:** [chunking-and-languages](chunking-and-languages.md).
- **DoD:** for each of the seven languages, a fixture file produces the expected `Chunk` / `Symbol` / `Edge` lists per a per-plugin snapshot test. The registry resolves an extension to the correct plugin; `extra_languages` from a fixture config loads and registers a synthetic plugin without engine changes.
- **Note on parallelism:** the seven plugins are independent of each other once the interface is fixed. The `/planner` pass for this phase should split it into one step per plugin (plus a foundational step for the interface and registry) and may dispatch coders in parallel.

### Phase 4 — Walker, indexer, `init`, `index build`

- **Delivers:**
  - File walker implementing every rule in [architecture](architecture.md)'s "Indexer walking" section: `.gitignore` honoring, default excludes, max-file-size, NUL-byte binary detection, symlink policy, UTF-8 + replace fallback.
  - Indexer pipeline: walk → dispatch to plugin → batch chunk texts → embed → insert into `chunks` / `chunks_fts` / `embeddings` / `symbols` / `edges` / `meta`.
  - `code_index init` subcommand: writes the skeleton `config.toml` from [config](config.md)'s "What `init` writes" section, plus the `.gitignore` for the index file. Idempotent with `--force` override.
  - `code_index index build` subcommand with the flags from [cli](cli.md) (`--root`, `--dry-run`, `--verbose`).
- **Depends on:** Phases 1, 2, 3.
- **Exercises:** [architecture](architecture.md) (Indexer walking), [cli](cli.md) (init, index build).
- **DoD:** `code_index init` followed by `code_index index build` against a small polyglot fixture project (one file per supported language, plus a `.gitignore`'d directory and a binary file) populates all expected tables with the expected row counts; the binary and ignored files are absent from the index.

### Phase 5 — Search

- **Delivers:**
  - FTS5 query path.
  - `sqlite-vec` cosine query path.
  - Parallel issue + RRF fusion with `k = 60` per [retrieval](retrieval.md) (fixed, not configurable).
  - Filter application to **both pools** before fusion (`--lang`, `--kind`, `--path`).
  - `code_index search` subcommand with all flags from [cli](cli.md), including `--mode bm25|dense|hybrid`.
- **Depends on:** Phases 1, 2, 3, 4.
- **Exercises:** [retrieval](retrieval.md), [cli](cli.md) (search).
- **DoD:** against the Phase-4 fixture, a known symbol-name query returns the expected `file:line`; a known conceptual query returns the expected chunk; `--mode bm25` and `--mode dense` each return their respective single-pool result list; `--mode hybrid` matches the default behavior.

### Phase 6 — Sync, symbols, graph, rebuild

- **Delivers:**
  - `code_index index sync` subcommand using mtime+size comparison against the `files` table; no git dependency. The `files` table is part of schema v1 (created by `0_to_1.py`); Phase 6 reads it but does not ship a migration.
  - `code_index index rebuild` subcommand (drop + build, gated by `--yes`).
  - `code_index symbols defs|refs` per [cli](cli.md) and the "Symbol identity" section of [chunking-and-languages](chunking-and-languages.md): substring by default, `--exact`, `--lang`, case-sensitive.
  - `code_index graph callers|deps` with lazy `dst_name`-to-`symbols.name` resolution per [storage](storage.md)'s "Edge resolution" section.
- **Depends on:** Phases 1, 2, 3, 4. Phase 5 is not required — sync, symbols, and graph do not depend on the search pipeline.
- **Exercises:** [cli](cli.md) (sync, rebuild, symbols, graph), [storage](storage.md) (edge resolution), [chunking-and-languages](chunking-and-languages.md) (symbol identity).
- **DoD:** edit one fixture file, run `code_index index sync`, verify only that file's rows changed; `code_index symbols defs <name>` returns expected hits with the right `scope`; `code_index graph callers <symbol>` returns the expected source chunks; `code_index graph deps <path>` returns expected target names, including any unresolved ones (the contract allows them).

### Phase 7 — `config show`, JSON polish

- **Delivers:**
  - `code_index config show` subcommand: prints resolved config + index meta (schema_version, embed_model) per [cli](cli.md). The Phase 1 stub is replaced with the full implementation here.
  - `--format json` final pass: every subcommand returns a stable JSON shape on stdout for success and the error envelope from [errors-and-exit-codes](errors-and-exit-codes.md) on failure. The shape is documented inline per subcommand.
- **Depends on:** Phases 1–6.
- **Exercises:** [cli](cli.md) (config show), [errors-and-exit-codes](errors-and-exit-codes.md) (JSON envelope), [config](config.md).
- **DoD:** every MVP subcommand under `--format json` round-trips through `json.loads`; the same subcommands under failure conditions emit a parseable error envelope.

## How `/planner` consumes this

- Each phase corresponds to one `/planner` invocation. The phase name becomes the feature name in `docs/plans/<NNN>.<feature>/`.
- The `/planner` pass should treat `mvp-phases.md` plus the architecture docs the phase exercises as its primary inputs.
- Step granularity within a phase is the planner's call; the phase DoD is the contract.
- A phase is finalized (per the architect skill's finalization workflow) only after the DoD passes.

## Implications

- Phase boundaries are the natural review checkpoints. The user can intervene between phases without losing context.
- A failed DoD in any phase blocks the next phase; foundation drift surfaces immediately at the boundary instead of propagating downstream.
- Adding a feature outside the seven phases is implicitly out-of-MVP and should land via a new architecture decision plus its own plan, not as a smuggled step in an existing phase.

## Open questions

None — phasing is committed. Per-phase planner decisions (step granularity, parallelism within Phase 3) are not architectural questions and live with the planner.
