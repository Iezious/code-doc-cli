# Storage

## Decision

The index is a **single SQLite file** per project, located at `docs/.helpers/index.sqlite`, with:

- `sqlite-vec` extension for dense vector storage and cosine search.
- FTS5 (built into SQLite) for BM25 lexical search.
- Regular tables for chunks, symbols, edges, and metadata.

The same file holds everything; there is no sidecar index, no separate vector store, no second database.

## Rationale

- **Portable.** One file copied or scp'd is a complete index. No server install, no schema migration tooling needed by consumers.
- **All retrieval kinds in one engine.** BM25 (FTS5) and dense (sqlite-vec) live in the same DB, queried in the same transaction — fusion in user-space is trivial.
- **WAL mode** allows concurrent reads while a writer is updating, which is enough for "index building in background, search in foreground" use cases.
- **SQLite is universal.** Every machine, every language, every CI runner can open it.

## Rejected alternatives

- **Qdrant / Weaviate / Milvus.** Separate process, separate ops surface. Unjustified at single-user scale.
- **LanceDB / Chroma local.** Decent, but adds a second storage primitive when SQLite + sqlite-vec already covers both vectors and BM25.
- **In-memory FAISS + JSON sidecar.** No durability story, no FTS, no symbol queries.
- **DuckDB with vector extension.** Plausible alternative, but tooling and integration are less mature than SQLite + sqlite-vec for this exact pattern.

## Schema sketch

Exact column types and indices are to be finalized at implementation time. The shape:

```
meta(
  key TEXT PRIMARY KEY,
  value TEXT
)
-- holds: schema_version, codedoc_version, last_commit, embed_model, embed_dim

chunks(
  id INTEGER PRIMARY KEY,
  path TEXT,
  language TEXT,
  project TEXT,
  start_line INTEGER,
  end_line INTEGER,
  kind TEXT,         -- function, type, module, state, event, class, ...
  name TEXT,         -- best-effort symbol name for the chunk
  scope TEXT,        -- enclosing scope (module path, state name, etc.)
  content TEXT,
  content_hash TEXT  -- for embedding cache
)

chunks_fts USING FTS5(content, name, scope, content='chunks', content_rowid='id')

embeddings USING vec0(
  chunk_id INTEGER PRIMARY KEY,
  embedding FLOAT[<dim>]
)

symbols(
  id INTEGER PRIMARY KEY,
  chunk_id INTEGER,
  name TEXT,
  kind TEXT,         -- def, ref
  line INTEGER
)

edges(
  src_chunk_id INTEGER,
  dst_name TEXT,     -- resolved later via symbols table
  kind TEXT,         -- import, call, listen, link_message, http, ...
  meta TEXT          -- JSON payload for language-specific extras
)
```

Indices on `chunks(path)`, `chunks(language)`, `symbols(name)`, `edges(dst_name)`, `edges(src_chunk_id)`.

## Schema versioning

- `meta.schema_version` is written at index creation.
- On every open, storage checks the running engine's expected version. Mismatch is **loud**: refuse to query and prompt for `codedoc index rebuild` or a documented migration.
- Migrations are forward-only and live in `codedoc.storage.migrations.<from>_to_<to>.py`.
- The version is bumped on any schema-affecting change, however small. Silent drift is the failure mode we are paying overhead to prevent.

## Embedding storage

- `embeddings` table dimension matches the **embedding model**, not the project config. Switching models means rebuild (or re-embed with conversion).
- `meta.embed_model` records which model produced the current embeddings. Mismatch with config is loud.
- `chunks.content_hash` enables a future embedding cache so unchanged chunks skip re-embed across rebuilds.

## Concurrency

- WAL mode is enabled at connection setup.
- Indexer takes a single write connection; readers (search, symbols, graph) use separate read connections.
- No long-running transactions in readers.

## Implications

- An index file is tied to a specific embedding model. Changing `embed_model` in config triggers a rebuild (or, in the future, a re-embed pass).
- Backups are trivial — copy the `.sqlite` file (plus `-wal` and `-shm` if present, or after checkpoint).
- The file should be gitignored. It is a build artifact.

## Open questions

- Whether to also persist a `files` table separately from `chunks` for fast "list files" queries, or derive from `chunks` via DISTINCT. Likely needed for graph/symbol indices to be efficient.
- Whether to vacuum on a schedule or after sync above a threshold of deletes. Deferred to implementation.
