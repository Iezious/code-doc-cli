# Architecture

## Decision

`code_index` is structured as a CLI front end over a small set of cooperating modules: a language-plugin layer, an indexer pipeline, a SQLite storage layer (with `sqlite-vec` and FTS5), an embedding backend, and a retrieval/symbols/graph query layer. All modules are in-process; there is no network component.

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

- **CLI** (`code_index.cli`) — `typer`-based entry point. Subcommands: `init`, `index build|sync`, `search`, `symbols`, `graph`, `config show`. See `cli.md`.
- **Config** (`code_index.config`) — loads `docs/.helpers/config.toml`, validates against schema version pin, exposes resolved settings.
- **Language plugins** (`code_index.languages.*`) — one module per language. Each implements `chunk`, `symbols`, and `imports`. Dispatch is by file extension. See `chunking-and-languages.md`.
- **Chunker** (`code_index.chunker`) — thin dispatcher that picks the language plugin for a path and returns a normalized `Chunk` list.
- **Embeddings** (`code_index.embeddings`) — backend interface; the MVP ships `fastembed` as the sole implementation. See [embeddings](embeddings.md).
- **Storage** (`code_index.storage`) — SQLite wrapper that owns connection lifecycle, loads the `sqlite-vec` extension, manages FTS5 tables, and runs schema migrations. See `storage.md`.
- **Indexer** (`code_index.indexer`) — walks roots respecting config ignores, calls chunker, batches embeddings, inserts rows. Returns counts and timings.
- **Sync** (`code_index.sync`) — incremental update via mtime+size comparison against the `files` table. Re-embeds only changed files, inserts new ones, removes vanished ones.
- **Search** (`code_index.search`) — runs FTS5 BM25 and `sqlite-vec` cosine queries in parallel, fuses with RRF, returns ranked chunks with `file:line`. See `retrieval.md`.
- **Symbols** (`code_index.symbols`) — pure index lookup over the stored symbols table. `defs`, `refs`. Powered by what plugins emitted at index time; symbol queries are index-only for determinism.
- **Graph** (`code_index.graph`) — queries the edges table for `callers`, `deps`. Per-language plugins decide what counts as an edge (imports, listen channels, etc.).

## Data flow

### Index build
1. CLI reads config, resolves roots and ignores.
2. Indexer walks files, dispatches each to its language plugin.
3. Plugin returns chunks, symbols, edges.
4. Indexer batches chunk texts to the embedding backend.
5. Storage inserts: `chunks`, `chunks_fts`, `embeddings` (vec table), `symbols`, `edges`, updates `meta`.

### Sync
1. Walker enumerates current project files (same ignore rules as `index build`).
2. For each walked file, compare mtime and size against the corresponding row in `files`:
   - Match → no action.
   - Differs → delete the file's existing rows from `chunks` / `chunks_fts` / `embeddings` / `symbols` / `edges`; re-chunk, re-embed, re-insert; update the `files` row.
   - Absent → chunk, embed, insert; add a row to `files`.
3. For each row in `files` whose path is not in the walked set, delete its rows from the five row-data tables and remove the `files` row.

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
- The `[code_index].ignores` key in `config.toml` (see [config](config.md)) **appends to** — never replaces — the default excludes and `.gitignore` rules.

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
- Live file watching (a future `code_index watch` command is possible but not in scope).
- Cross-project federated search — each project has its own index; the doc-gen pipeline composes results at the orchestrator layer.

## Open questions

None pinned here.
