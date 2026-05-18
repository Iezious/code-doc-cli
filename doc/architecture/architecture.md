# Architecture

## Decision

`codedoc` is structured as a CLI front end over a small set of cooperating modules: a language-plugin layer, an indexer pipeline, a SQLite storage layer (with `sqlite-vec` and FTS5), an embedding backend, and a retrieval/symbols/graph query layer. All modules are in-process; there is no network component.

## High-level shape

```
                +--------------------+
                |       CLI          |
                |  (typer subcmds)   |
                +---------+----------+
                          |
   +----------------------+----------------------+
   |              |              |               |
+--v---+   +------v-----+  +-----v-----+   +-----v-----+
| init |   |  indexer   |  |  search   |   | symbols/  |
|      |   |  + sync    |  |  (hybrid) |   | graph     |
+------+   +------+-----+  +-----+-----+   +-----+-----+
                  |              |               |
                  v              v               v
            +-----+---+    +-----+----+    +-----+----+
            | chunker |    |  store   |    |  store   |
            +----+----+    +-----+----+    +----------+
                 |               |
                 v               v
        +--------+-----+   +-----+-----+
        | language     |   | embeddings|
        | plugins (7)  |   |  backend  |
        +--------------+   +-----------+
                 |
                 v
        source files on disk
```

## Components

- **CLI** (`code_doc_cli.cli`) — `typer`-based entry point. Subcommands: `init`, `index build|sync`, `search`, `symbols`, `graph`, `config show`. See `cli.md`.
- **Config** (`code_doc_cli.config`) — loads `docs/.helpers/config.toml`, validates against schema version pin, exposes resolved settings.
- **Language plugins** (`code_doc_cli.languages.*`) — one module per language. Each implements `chunk`, `symbols`, and `imports`. Dispatch is by file extension. See `chunking-and-languages.md`.
- **Chunker** (`code_doc_cli.chunker`) — thin dispatcher that picks the language plugin for a path and returns a normalized `Chunk` list.
- **Embeddings** (`code_doc_cli.embeddings`) — backend interface with `fastembed` default and Voyage as an opt-in extra. See `embeddings.md`.
- **Storage** (`code_doc_cli.storage`) — SQLite wrapper that owns connection lifecycle, loads the `sqlite-vec` extension, manages FTS5 tables, and runs schema migrations. See `storage.md`.
- **Indexer** (`code_doc_cli.indexer`) — walks roots respecting config ignores, calls chunker, batches embeddings, inserts rows. Returns counts and timings.
- **Sync** (`code_doc_cli.sync`) — git-aware incremental update. Diffs against the last indexed commit (or mtimes for non-git trees), re-embeds only changed chunks.
- **Search** (`code_doc_cli.search`) — runs FTS5 BM25 and `sqlite-vec` cosine queries in parallel, fuses with RRF, returns ranked chunks with `file:line`. See `retrieval.md`.
- **Symbols** (`code_doc_cli.symbols`) — pure index lookup over the stored symbols table. `defs`, `refs`. Powered by what plugins emitted at index time; symbol queries are index-only for determinism.
- **Graph** (`code_doc_cli.graph`) — queries the edges table for `callers`, `deps`. Per-language plugins decide what counts as an edge (imports, listen channels, etc.).

## Data flow

### Index build
1. CLI reads config, resolves roots and ignores.
2. Indexer walks files, dispatches each to its language plugin.
3. Plugin returns chunks, symbols, edges.
4. Indexer batches chunk texts to the embedding backend.
5. Storage inserts: `chunks`, `chunks_fts`, `embeddings` (vec table), `symbols`, `edges`, updates `meta`.

### Sync
1. Storage reads last-indexed commit hash from `meta`.
2. Sync gets `git diff --name-only <last>..HEAD`. If not a git tree, falls back to mtime comparison.
3. For each changed file: delete old rows, re-chunk, re-embed, re-insert.
4. Update `meta.last_commit`.

### Search
1. CLI parses query and filters (`--lang`, `--k`, `--project`, etc.).
2. Search module issues an FTS5 query and a `vec_search` query in parallel.
3. Results are fused with RRF (`k=60` default).
4. Top-N returned with `file:line` and chunk text excerpt.

## Indexer walking

The walker is the first stage of the indexer pipeline; it decides which files reach the chunker. The rules below are pinned so plugin authors and config writers can reason about coverage.

### Ignore sources

- **`.gitignore`** is honored by default when the project root contains a `.git` directory. Honored at every level — root and any nested `.gitignore`. When there is no `.git`, the `.gitignore` mechanism is silently inactive (no warning; many polyglot trees are not git-managed).
- **Built-in default excludes**, always applied regardless of `.gitignore`:
  - `.git/`, `.hg/`, `.svn/`
  - `node_modules/`, `bower_components/`
  - `.venv/`, `venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`
  - `dist/`, `build/`, `out/`, `target/`, `bin/`, `obj/`
  - `.idea/`, `.vscode/`
  - `docs/.helpers/` itself — the index lives here; never index your own index.
- The `[codedoc].ignores` key in `config.toml` (see [config](config.md)) **appends to** — never replaces — the default excludes and `.gitignore` rules.

### File-level filters

- **Max file size:** 1 MiB by default. Files above the cap are skipped with a stderr warning in default mode; in `--strict` mode this raises code `41 / io.oversize` (see [errors-and-exit-codes](errors-and-exit-codes.md)).
- **Binary detection:** a file is treated as binary if (a) its extension is not registered with any active language plugin, OR (b) the first 8 KiB contain a NUL byte. Binary files are not opened for chunking. The extension check runs first (cheap); the NUL probe runs only for unknown-extension files that could still be plaintext.
- **Encoding:** files are decoded as UTF-8. On `UnicodeDecodeError` the walker retries with UTF-8 + `errors="replace"` and emits a stderr warning. No latin-1 fallback, no chardet — a deterministic decode keeps the chunker working without inventing data.

### Symlink policy

- Symlinks **to files** are followed.
- Symlinks **to directories** are not followed. This prevents loops and accidental traversal into unrelated trees outside the configured roots.
- Inode-set loop detection is unnecessary because directory symlinks are skipped outright.
- If a symlink target is missing, the walker warns on stderr and skips.

### Rejected alternatives

- **Replacing built-in excludes with config-only excludes.** Too easy to misconfigure into indexing `node_modules/`; the cost of the duplicated list is small.
- **Following directory symlinks with loop detection.** Most projects do not need it, and the failure mode (silently indexing an unrelated tree) is worse than the inconvenience of adding a `roots` entry by hand.
- **chardet / cchardet for encoding sniffing.** Extra dep and nondeterministic across versions; deterministic decode wins.
- **No max file size.** Generated single-file artifacts (huge bundles, vendored libs) would dominate the index and waste embedding budget.

## Process model

- Single-process, single-user. No daemon, no server.
- Index files use SQLite WAL mode to allow read-during-write.
- Embedding is the hot loop; batching is the main lever.

## Non-goals

- Distributed indexing.
- Live file watching (a future `codedoc watch` command is possible but not in scope).
- Cross-project federated search — each project has its own index; the doc-gen pipeline composes results at the orchestrator layer.

## Open questions

- Whether `sync` should also fall back to file hash comparison (more robust than mtime) when git is absent. Likely yes; deferred to implementation.
