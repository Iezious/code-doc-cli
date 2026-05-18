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
-- holds: schema_version, code_index_version, last_commit, embed_model, embed_dim

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
  content TEXT
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

## Edge resolution

Edges are **resolved lazily at query time**, not at index-write time.

- Language plugins emit edges with `dst_name` as a free-form string — symbol name, module path, channel id, URL, whatever the plugin's edge `kind` defines. Plugins do not look up symbol ids when emitting edges.
- Resolution happens inside `graph callers` / `graph deps` by joining `edges.dst_name` against `symbols.name`, with any filters from the query (language, kind, etc.) applied. The query layer is the only place that knows how to interpret resolution semantics; the storage layer keeps the raw strings.

Consequences:

- **Renames** are handled correctly without rewriting `edges` rows. The next `index sync` updates the affected symbol rows; subsequent queries see the new resolution.
- **Deletions** leave dangling `dst_name` strings; the join naturally returns no match. The query layer can report these as unresolved on request — useful for agents asking "what call sites point at nothing?".
- **Cross-file and cross-language edges** need no special handling — symbol lookup is global by name within the chosen filters.
- **Performance:** the `symbols(name)` index is the hot path. For a 50k-chunk index this stays well inside the latency budget in [retrieval](retrieval.md).

### Rejected resolution strategies

- **Eager resolution at write time** (storing `dst_chunk_id` directly). Forces re-resolve on every sync that touches a referenced symbol; breaks under renames; and forces all plugins to participate in a single symbol-id arena before any of them can write edges.
- **A separate post-pass that resolves edges after the indexer completes.** Doubles the index-build time for marginal query-time gain; the resolution cost is amortized across queries that actually need it.

## Schema versioning

- `meta.schema_version` is written at index creation.
- On every open, storage checks the running engine's expected version. Mismatch is **loud**: refuse to query and prompt for `code_index index rebuild` or a documented migration.
- Migrations are forward-only and live in `code_index.storage.migrations.<from>_to_<to>.py`.
- The version is bumped on any schema-affecting change, however small. Silent drift is the failure mode we are paying overhead to prevent.

## Embedding storage

- `embeddings` table dimension matches the **embedding model**, not the project config. Switching models means rebuild (or re-embed with conversion).
- `meta.embed_model` records which model produced the current embeddings. Mismatch with config is loud.

An embedding cache keyed by chunk content hash is **deferred** (see [mvp-scope](mvp-scope.md)). The supporting `chunks.content_hash` column lands together with the cache feature via a schema bump, not as a dormant column.

## Concurrency

- WAL mode is enabled at connection setup.
- Indexer takes a single write connection; readers (search, symbols, graph) use separate read connections.
- No long-running transactions in readers.

Readers see a **SQLite snapshot pinned at connection time**: a reader observes a consistent view of the database as of the moment it opened its connection, and concurrent writes by an indexer or `index sync` are invisible until that reader closes and reopens. Long-running agent loops (planner-explorer iterations, multi-phase doc generation) that want to pick up newer index state must reopen between phases; the CLI exits between invocations, so an agent that issues one `code_index` call per query already gets fresh state naturally. This is what makes determinism affordable in practice — a single planner-explorer iteration sees one consistent index even if a `code_index index sync` is racing in the background, and there is no read-side coordination cost for the common case. See [docs-generation-pipeline](docs-generation-pipeline.md) for why this matters to the consumer.

## Implications

- An index file is tied to a specific embedding model. Changing `embed_model` in config triggers a rebuild (or, in the future, a re-embed pass).
- Backups are trivial — copy the `.sqlite` file (plus `-wal` and `-shm` if present, or after checkpoint).
- The file should be gitignored. It is a build artifact.

## Open questions

None pinned here. A separate `files` table and vacuum scheduling were demoted to [roadmap](roadmap.md).
