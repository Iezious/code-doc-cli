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

- **CLI** (`codedoc.cli`) — `typer`-based entry point. Subcommands: `init`, `index build|sync`, `search`, `symbols`, `graph`, `config show`. See `cli.md`.
- **Config** (`codedoc.config`) — loads `docs/.helpers/config.toml`, validates against schema version pin, exposes resolved settings.
- **Language plugins** (`codedoc.languages.*`) — one module per language. Each implements `chunk`, `symbols`, and `imports`. Dispatch is by file extension. See `chunking-and-languages.md`.
- **Chunker** (`codedoc.chunker`) — thin dispatcher that picks the language plugin for a path and returns a normalized `Chunk` list.
- **Embeddings** (`codedoc.embeddings`) — backend interface with `fastembed` default and Voyage as an opt-in extra. See `embeddings.md`.
- **Storage** (`codedoc.storage`) — SQLite wrapper that owns connection lifecycle, loads the `sqlite-vec` extension, manages FTS5 tables, and runs schema migrations. See `storage.md`.
- **Indexer** (`codedoc.indexer`) — walks roots respecting config ignores, calls chunker, batches embeddings, inserts rows. Returns counts and timings.
- **Sync** (`codedoc.sync`) — git-aware incremental update. Diffs against the last indexed commit (or mtimes for non-git trees), re-embeds only changed chunks.
- **Search** (`codedoc.search`) — runs FTS5 BM25 and `sqlite-vec` cosine queries in parallel, fuses with RRF, returns ranked chunks with `file:line`. See `retrieval.md`.
- **Symbols** (`codedoc.symbols`) — lexical lookup over the stored symbols table. `defs`, `refs`. Powered by what plugins emitted at index time, optionally falls back to ripgrep for live queries.
- **Graph** (`codedoc.graph`) — queries the edges table for `callers`, `deps`. Per-language plugins decide what counts as an edge (imports, listen channels, etc.).

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
- Whether to cache embeddings keyed by chunk content hash so re-chunking same text avoids re-embed. Likely yes; cheap insurance.
